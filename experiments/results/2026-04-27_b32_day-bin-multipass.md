# 2026-04-27 B32 day-bin + 다중 패스 cap fill

## 배경

B30 (점수+시간분산) + B31 (timestamp 파서 fix) 머지 후 LIVE 수집 분석에서
드러난 두 가지 비효율:

1. **선별 95 < max_posts 120** — hour offset +11~+14 같은 후보 0인 시간대가
   존재하면 cap 못 채워서 max_posts 미달.
2. **date-only 글의 hour-bin 인공 집중** — `'04.26'` 같은 MM.DD 만 있는 글이
   12:00 으로 떨어져 한 hour bin (예: hour -6) 에 93개 몰리고 cap=6 으로
   87개가 손실. 점수 4000+ 짜리도 대거 누락.

## 결정

### (A) date-only 글의 별도 day-bin
- `_bin_key()` helper 신설. timestamp_parsed 와 raw timestamp 문자열로 bin 분류
- 분류:
  - `("unknown",)`: timestamp 파싱 실패
  - `("day", date)`: MM.DD / YYYY.MM.DD 만 있는 (HH:MM 없음) 글
  - `("hour", offset)`: HH:MM 까지 정확한 글의 시간 offset bin
- bin 종류별 base cap 분리:
  - hour: `per_hour_cap=6`
  - day:  `per_day_cap=24` (hour 평균 ~2.5 의 약 10배. 한 날짜 글이 통째 손실되지 않게)
  - unknown: `max_posts × unknown_cap_ratio` (=30 @ max=120, ratio=0.25)

### (B) 다중 패스 cap fill
- pass 1: base cap → 시간 분산 우선, 모든 bin 균등 기회
- pass 2: cap × 2 → pass1 의 하드 cap 으로 거른 hot bin 추가 흡수
- pass 3: cap 무한 (점수순) → max_posts 미달 시 잔여 후보로 마지막 fill

같은 url 은 한 번만 채택.

## 구현

`pipeline/scraper.py`
- `_DATE_ONLY_RE_SHORT`, `_DATE_ONLY_RE_LONG` — date-only 패턴 컴파일된 정규식
- `_bin_key(post, broadcast_dt)` — 분류 helper
- `_select_top_diverse()` — `per_day_cap` 파라미터 추가, 내부 `_try_take(cap_factor)`
  헬퍼로 3패스 진행

## 검증

`python experiments/b30_score_time_diversity.py` — 11/11 PASS
1. score formula
2a. 경쟁 bin 이 있으면 hot bin 도 cap 보호 (hot 30 + other 6, max 12 → 6+6)
2b. 단일 bin 만 있을 때 다중 패스로 max_posts 달성
3. bin 내 점수 우선
4. 3 bin 균등 분산 (각 6개씩, max=18)
5. unknown bucket pass1 cap 작동
5b. unknown 만 있을 때 다중 패스로 max_posts 충족
6. broadcast_dt=None → wall-clock hour fallback + 다중 패스
7. max_posts > 후보 → 모두 반환
8. **date-only 글이 day-bin 으로 분류되어 hour 에 안 몰림 (50/50 채택)**
9. **day-bin cap 이 hour-bin 보호 (high-score date-only 50 + hour 30, max 40 → day 34, hour 6)**

회귀:
- `experiments/b27_fmkorea_chromium.py` 6/6 PASS
- `experiments/b31_timestamp_parser.py` 9/9 PASS
- `experiments/test_manual_community_override.py` PASS

## LIVE 재검증

`python experiments/b30_live_collection.py` — chromium 백엔드, 키워드 1개 × 20페이지

| 메트릭 | B30 직후 | B31(timestamp fix) 후 | **B32 (이번)** |
|---|---|---|---|
| 선별 개수 | 30 (cap unknown=30) | 95 (시간 분포 살아남) | **120 (max 정확 충족)** |
| hour -6 (date-only 04.26) | — | 6 (cap=6) | **31 (day-bin)** |
| 누락 top score | — | 4166 | **2066 (-50%)** |
| 선별 평균 점수 | — | 2813 | **2955** |
| 시간 분포 | 부재 (전부 unknown) | -6~+19 hour 분산 | hour 분산 + day-bin 분리 |

## 운영 메모

- `pipeline_config.json` 의 `fmkorea_max_posts=120` 가 이제 실제로 달성됨.
- `per_day_cap=24` 는 코드 상수. 운영 데이터로 재튜닝 가능 — 글이 너무 며칠
  지난 것까지 들어오면 16~20 으로 하향, 부족하면 30+ 로 상향.
- 다중 패스의 pass3 (cap 무한) 는 max_posts 보장하는 안전망. 후보 부족해도
  이상한 lock 없이 가용 글 다 반환.
- 점수 가중치 (10/5) 는 그대로. 운영에서 community_matcher hot_segments
  결과 보고 추후 튜닝.
