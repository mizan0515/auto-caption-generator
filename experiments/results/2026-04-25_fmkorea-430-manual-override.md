# 2026-04-25 fmkorea 430 Manual Override

## 배경

- `12890507` 처리 중 `fmkorea 검색: '탬탬'` 직후 `HTTP 430 (rate limit/anti-bot)` 발생.
- 현재 구현은 430/429를 anti-bot 으로 보고 즉시 중단한다.
- 같은 세션/헤더로 재시도하는 것은 우회가 아니라 실패 반복에 가깝다.

## 결정

- 자동 스크랩 경로에서 430 자체를 “우회”하지 않는다.
- 대신 수동 수집 결과를 파이프라인에 주입할 수 있는 override 경로를 추가한다.

## 구현

- `pipeline/scraper.py`
  - `load_manual_community_posts()` 추가
  - 파일 경로: `work/<video_no>/<video_no>_community.manual.json`
- `pipeline/main.py`
  - 자동 캐시/스크랩보다 먼저 수동 override를 확인
  - 존재 시 fmkorea 네트워크 스크랩 스킵
- `README.md`
  - 수동 override 사용법 문서화

## 검증

- `python experiments/test_manual_community_override.py`
- 기대 결과: `manual community override ok`

## 운영 메모

- 브라우저로 사람이 직접 본 결과를 이 JSON으로 넣으면 430이 떠도 현재 VOD 작업은 계속 완성할 수 있다.
- anti-bot을 코드로 우회하는 대신, 사용자 주도 manual seed를 first-class 경로로 만든 것이다.
