"""Claude가 추천한 번호로 동행복권 로또 6/45를 자동 구매하는 봇.

흐름:
    1. 동행복권 로그인 (requests.Session)
    2. Anthropic Claude API에 추천 번호를 요청 (5게임)
    3. execBuy.do 로 수동 모드 구매
    4. (선택) Discord 웹훅으로 결과 알림

환경 변수:
    DHLOTTERY_USER_ID, DHLOTTERY_PASSWORD : 동행복권 계정
    ANTHROPIC_API_KEY                    : Claude API 키
    LOTTO_GAME_COUNT (선택, 기본 5)       : 구매 게임 수 (1~5)
    DISCORD_WEBHOOK_URL (선택)            : 알림용 웹훅
    CLAUDE_MODEL (선택, 기본 claude-opus-4-7) : 추천에 사용할 모델
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass

import requests
from anthropic import Anthropic

LOGIN_URL = "https://www.dhlottery.co.kr/userSsl.do?method=login"
MAIN_URL = "https://dhlottery.co.kr/common.do?method=main"
ROUND_INFO_URL = "https://www.dhlottery.co.kr/common.do?method=main"
READY_URL = "https://ol.dhlottery.co.kr/olotto/game/egovUserReadySocket.json"
BUY_URL = "https://ol.dhlottery.co.kr/olotto/game/execBuy.do"
GAME_PAGE_URL = "https://ol.dhlottery.co.kr/olotto/game/game645.do"
BALANCE_URL = "https://dhlottery.co.kr/userSsl.do?method=myPage"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lotto-bot")


@dataclass
class PurchaseResult:
    ok: bool
    round_no: int | None
    games: list[list[int]]
    message: str
    raw: dict | None = None


class DhLotteryClient:
    """동행복권 6/45 수동 구매 클라이언트."""

    def __init__(self, user_id: str, password: str) -> None:
        self.user_id = user_id
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def login(self) -> None:
        self.session.get(MAIN_URL, timeout=10)
        payload = {
            "returnUrl": MAIN_URL,
            "userId": self.user_id,
            "password": self.password,
            "checkSave": "off",
            "newsEventYn": "",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.dhlottery.co.kr",
            "Referer": "https://dhlottery.co.kr/user.do?method=login",
        }
        resp = self.session.post(LOGIN_URL, data=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        if "비밀번호" in resp.text or "잘못" in resp.text or "FailLogin" in resp.text:
            raise RuntimeError("로그인 실패: 아이디/비밀번호를 확인하세요.")
        log.info("로그인 성공: %s", self.user_id)

    def _ready(self) -> str:
        """JSESSIONID 발급 + 회차 정보 확인. JSESSIONID 문자열 반환."""
        resp = self.session.post(READY_URL, headers={"Referer": GAME_PAGE_URL}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        jsession = data.get("ready_ip") or self.session.cookies.get("JSESSIONID")
        if not jsession:
            raise RuntimeError("JSESSIONID 획득 실패")
        return jsession

    def _direct_ip(self) -> str:
        try:
            return requests.get("https://api.ipify.org", timeout=5).text.strip()
        except Exception:
            return "127.0.0.1"

    def buy(self, games: list[list[int]]) -> PurchaseResult:
        if not 1 <= len(games) <= 5:
            raise ValueError("게임 수는 1~5 사이여야 합니다.")
        for g in games:
            if len(g) != 6 or len(set(g)) != 6 or any(n < 1 or n > 45 for n in g):
                raise ValueError(f"잘못된 번호 조합: {g}")

        jsession = self._ready()
        direct = self._direct_ip()

        param = []
        for idx, nums in enumerate(games):
            sorted_nums = sorted(nums)
            param.append({
                "genType": "1",  # 수동
                "arrGameChoiceNum": [",".join(f"{n:02d}" for n in sorted_nums)],
                "alpabet": chr(ord("A") + idx),
            })

        body = {
            "round": "",  # 빈 값이면 서버가 다음 회차로 처리
            "direct": direct,
            "nBuyAmount": str(1000 * len(games)),
            "param": json.dumps(param, ensure_ascii=False),
            "gameCnt": str(len(games)),
        }
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://ol.dhlottery.co.kr",
            "Referer": GAME_PAGE_URL,
            "JSESSIONID": jsession,
        }
        resp = self.session.post(BUY_URL, data=body, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("result", {})
        ok = result.get("resultMsg", "").upper() == "SUCCESS"
        round_no = result.get("buyRound") or result.get("round")
        try:
            round_no = int(round_no) if round_no is not None else None
        except (TypeError, ValueError):
            round_no = None
        message = result.get("resultMsg", "UNKNOWN")
        return PurchaseResult(ok=ok, round_no=round_no, games=games, message=message, raw=data)

    def balance(self) -> int | None:
        resp = self.session.get(BALANCE_URL, timeout=10)
        m = re.search(r'예치금[^0-9]*([0-9,]+)\s*원', resp.text)
        if not m:
            return None
        return int(m.group(1).replace(",", ""))


# ---------- Claude 추천 ----------

NUMBER_PATTERN = re.compile(r"\b([1-9]|[1-3][0-9]|4[0-5])\b")


def recommend_numbers(game_count: int, model: str) -> list[list[int]]:
    """Claude에게 6/45 번호 game_count세트를 추천받아 정수 리스트로 반환."""
    client = Anthropic()
    prompt = (
        f"한국 로또 6/45 번호를 {game_count}세트 추천해줘.\n"
        "각 세트는 1~45 사이 서로 다른 정수 6개로 구성되고, 오름차순으로 정렬해.\n"
        "응답은 반드시 JSON 배열만 출력해. 예: [[1,7,12,23,34,40], ...]\n"
        "설명, 코드블록, 주석 금지. 순수 JSON만."
    )
    msg = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    games = _parse_games(text, game_count)
    if not games:
        raise RuntimeError(f"Claude 추천 파싱 실패: {text!r}")
    log.info("Claude 추천 번호: %s", games)
    return games


def _parse_games(text: str, expected: int) -> list[list[int]]:
    try:
        cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        if isinstance(data, list) and all(isinstance(g, list) for g in data):
            return [_validate_set(g) for g in data[:expected]]
    except (json.JSONDecodeError, ValueError):
        pass

    games: list[list[int]] = []
    for line in text.splitlines():
        nums = [int(n) for n in NUMBER_PATTERN.findall(line)]
        nums = list(dict.fromkeys(nums))
        if len(nums) >= 6:
            games.append(_validate_set(nums[:6]))
        if len(games) == expected:
            break
    return games


def _validate_set(nums: list[int]) -> list[int]:
    s = sorted(set(int(n) for n in nums))
    if len(s) != 6 or s[0] < 1 or s[-1] > 45:
        raise ValueError(f"유효하지 않은 번호 세트: {nums}")
    return s


# ---------- 알림 ----------

def notify_discord(webhook: str, result: PurchaseResult, balance_after: int | None) -> None:
    games_text = "\n".join(
        f"  {chr(ord('A') + i)}: {' '.join(f'{n:02d}' for n in g)}"
        for i, g in enumerate(result.games)
    )
    title = "✅ 로또 자동구매 성공" if result.ok else "❌ 로또 자동구매 실패"
    lines = [title]
    if result.round_no:
        lines.append(f"회차: {result.round_no}")
    lines.append("Claude 추천 번호:")
    lines.append(games_text)
    lines.append(f"메시지: {result.message}")
    if balance_after is not None:
        lines.append(f"잔액: {balance_after:,}원")
    payload = {"content": "\n".join(lines)}
    try:
        requests.post(webhook, json=payload, timeout=10)
    except Exception as e:
        log.warning("Discord 알림 실패: %s", e)


# ---------- 진입점 ----------

def main() -> int:
    user_id = os.environ.get("DHLOTTERY_USER_ID")
    password = os.environ.get("DHLOTTERY_PASSWORD")
    if not (user_id and password):
        log.error("DHLOTTERY_USER_ID / DHLOTTERY_PASSWORD 환경변수가 필요합니다.")
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY 환경변수가 필요합니다.")
        return 2

    game_count = int(os.environ.get("LOTTO_GAME_COUNT", "5"))
    model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-7")
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")

    games = recommend_numbers(game_count, model)

    client = DhLotteryClient(user_id, password)
    client.login()
    result = client.buy(games)
    balance_after = client.balance()

    log.info("구매 결과: ok=%s round=%s message=%s",
             result.ok, result.round_no, result.message)
    if balance_after is not None:
        log.info("잔액: %s원", f"{balance_after:,}")

    if webhook:
        notify_discord(webhook, result, balance_after)

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
