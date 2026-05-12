"""외부에서 입력받은 번호로 동행복권 로또 6/45를 자동 구매하는 봇.

사용법:
    python lotto_bot.py "1,7,12,23,34,40" "3,9,15,22,31,45" ...
        # 인자 1개당 1게임. 1~5게임까지 가능. 게임당 1,000원.

    python lotto_bot.py --stdin
        # stdin으로 JSON 배열 입력 (예: [[1,7,12,23,34,40], ...])

환경 변수:
    DHLOTTERY_USER_ID, DHLOTTERY_PASSWORD : 동행복권 계정 (필수)
    DISCORD_WEBHOOK_URL (선택)            : 알림용 웹훅
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass

import requests

LOGIN_URL = "https://www.dhlottery.co.kr/userSsl.do?method=login"
MAIN_URL = "https://dhlottery.co.kr/common.do?method=main"
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
            "round": "",
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


# ---------- 입력 파싱 ----------

def parse_game(raw: str) -> list[int]:
    """'1,7,12,23,34,40' 또는 '1 7 12 23 34 40' 형식을 6개 정수 리스트로."""
    nums = [int(t) for t in re.split(r"[,\s]+", raw.strip()) if t]
    s = sorted(set(nums))
    if len(nums) != 6 or len(s) != 6 or s[0] < 1 or s[-1] > 45:
        raise ValueError(f"잘못된 번호 조합: {raw!r} (1~45 사이 서로 다른 정수 6개 필요)")
    return s


def parse_games_from_stdin() -> list[list[int]]:
    text = sys.stdin.read().strip()
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("stdin은 JSON 배열이어야 합니다.")
    games: list[list[int]] = []
    for g in data:
        if isinstance(g, str):
            games.append(parse_game(g))
        elif isinstance(g, list):
            games.append(parse_game(",".join(str(n) for n in g)))
        else:
            raise ValueError(f"지원하지 않는 게임 형식: {g!r}")
    return games


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
    lines.append("구매 번호:")
    lines.append(games_text)
    lines.append(f"메시지: {result.message}")
    if balance_after is not None:
        lines.append(f"잔액: {balance_after:,}원")
    try:
        requests.post(webhook, json={"content": "\n".join(lines)}, timeout=10)
    except Exception as e:
        log.warning("Discord 알림 실패: %s", e)


# ---------- 진입점 ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="동행복권 로또 6/45 자동 구매")
    parser.add_argument(
        "games",
        nargs="*",
        help='게임 1개당 인자 1개. 예: "1,7,12,23,34,40" "3,9,15,22,31,45"',
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="stdin에서 JSON 배열로 게임 입력",
    )
    args = parser.parse_args(argv)

    user_id = os.environ.get("DHLOTTERY_USER_ID")
    password = os.environ.get("DHLOTTERY_PASSWORD")
    if not (user_id and password):
        log.error("DHLOTTERY_USER_ID / DHLOTTERY_PASSWORD 환경변수가 필요합니다.")
        return 2

    if args.stdin:
        games = parse_games_from_stdin()
    elif args.games:
        games = [parse_game(g) for g in args.games]
    else:
        parser.error("게임 번호를 인자 또는 --stdin으로 전달하세요.")
        return 2

    log.info("구매할 번호: %s", games)

    client = DhLotteryClient(user_id, password)
    client.login()
    result = client.buy(games)
    balance_after = client.balance()

    log.info("구매 결과: ok=%s round=%s message=%s",
             result.ok, result.round_no, result.message)
    if balance_after is not None:
        log.info("잔액: %s원", f"{balance_after:,}")

    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook:
        notify_discord(webhook, result, balance_after)

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
