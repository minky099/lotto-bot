# 클로드 로또 자동 구매 봇

매주 Claude(Anthropic API)가 추천하는 6/45 로또 번호 5게임을 동행복권에서 자동으로 구매하는 한 파일짜리 봇.

참고:
- https://github.com/roeniss/dhlottery-api
- https://github.com/techinpark/lottery-bot

## 동작
1. 동행복권 로그인
2. Claude API에 추천 번호 N세트 요청
3. `execBuy.do` 수동 모드로 그대로 구매
4. (선택) Discord 웹훅으로 결과 알림

## 사전 준비
- 동행복권 계정 + 예치금 입금 (게임당 1,000원)
- Anthropic API 키 (`ANTHROPIC_API_KEY`)
- 구매 가능 시간(매주 월~토 06:00~22:00, 토 추첨일은 20:00까지)

## 로컬 실행
```bash
pip install -r requirements.txt
cp .env.example .env  # 값 채우기
set -a; source .env; set +a
python lotto_bot.py
```

## GitHub Actions 자동 실행
1. 이 저장소를 fork 후 Settings → Secrets and variables → Actions에 등록:
   - `DHLOTTERY_USER_ID`, `DHLOTTERY_PASSWORD`, `ANTHROPIC_API_KEY`
   - (선택) `DISCORD_WEBHOOK_URL`
2. Variables에 `LOTTO_GAME_COUNT`(기본 5), `CLAUDE_MODEL`(기본 `claude-opus-4-7`) 설정 가능
3. `.github/workflows/buy.yml`이 매주 토요일 11:00 KST에 자동 실행. 수동 실행은 Actions 탭에서 `Run workflow`.

## 주의
- 동행복권 약관/자동화 정책을 직접 확인하고 본인 책임 하에 사용.
- 비밀번호와 API 키는 절대 커밋하지 말 것 (`.env`는 gitignore 처리됨).
