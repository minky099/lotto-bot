# 로또 자동 구매 봇

LLM(예: Claude)이 따로 생성한 6/45 번호를 입력받아 동행복권에서 자동 구매하는 한 파일짜리 봇.

참고:
- https://github.com/roeniss/dhlottery-api
- https://github.com/techinpark/lottery-bot

## 동작
1. CLI 인자 또는 stdin(JSON)으로 번호 게임을 입력받음
2. 동행복권 로그인
3. `execBuy.do` 수동 모드로 그대로 구매
4. (선택) Discord 웹훅으로 결과 알림

## 사전 준비
- 동행복권 계정 + 예치금 입금 (게임당 1,000원, 최대 5게임)
- 구매 가능 시간: 매주 월~토 06:00~22:00, 토 추첨일은 20:00까지

## 로컬 실행
```bash
pip install -r requirements.txt
cp .env.example .env  # 값 채우기
set -a; source .env; set +a

# 인자 방식 (게임 1개당 인자 1개)
python lotto_bot.py "1,7,12,23,34,40" "3,9,15,22,31,45"

# stdin 방식 (JSON 배열)
echo '[[1,7,12,23,34,40],[3,9,15,22,31,45]]' | python lotto_bot.py --stdin

# dry-run (실제 구매 없이 번호 검증만; 로그인/HTTP 호출 안 함)
python lotto_bot.py --dry-run "1,7,12,23,34,40" "3,9,15,22,31,45"

# 로그인 테스트 (로그인 성공 여부와 잔액만 확인; 구매 안 함)
python lotto_bot.py --login-only
```

## 주의
- 동행복권 약관/자동화 정책을 직접 확인하고 본인 책임 하에 사용.
- 비밀번호와 자격증명은 절대 커밋하지 말 것 (`.env`는 gitignore 처리됨).
