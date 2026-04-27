# 2026-04-27 B30 fmkorea 점수화 + 시간 분산 선별

## 배경

`scrape_fmkorea()` 의 최종 cap 이 단순 `unique_posts[:max_posts]` 였다.
fmkorea 검색 결과 정렬은 보통 시간 desc 라, **방송 직후 1시간** 같은 hot
시간대에 글이 많이 쌓이면 그 시간대만 120개로 다 채우고 그 전후 시간대의
화제 포착이 누락되는 구조적 한계가 있었다.

또한 모든 글을 동등하게 다뤄서, 댓글이 많이 달린 hot post 와 단순 댓글 1개
짜리 글이 같은 자격으로 cap 안에 들어가는 문제도 있었다.

## 결정

1. **점수 공식**: `score = views + comments*10 + likes*5`
   - comments 가 가장 강한 신호 (적극적 반응)
   - likes 는 긍정적 동의 (조회보다 강하지만 댓글보다 약함)
   - views 는 baseline 1
2. **시간 분산**: 방송 ±24h 윈도우를 시간 단위 bin (48개) 으로 나누고
   per-hour cap 으로 한 시간대 쏠림 방지.
3. **그리디 선택**: 점수 내림차순 순회 → 해당 시간 bin 이 cap 미만이면
   채택, 아니면 skip → max_posts 도달 시 종료.
4. **unknown bucket**: timestamp 파싱 실패 글은 별도 cap (max_posts*25%) 으로
   분리. 시간을 알 수 없는 글이 결과를 잠식하지 않도록.

## 파라미터

- `fmkorea_max_pages: 6 → 20` (더 많은 후보 확보)
- `fmkorea_max_posts: 80 → 120`
- `per_hour_cap: 6` — 평균 2.5(120/48) 의 2.4x. hot hour 가 비대해도 다른
  시간대 손실 최소화.
- `unknown_cap_ratio: 0.25` — 120 기준 unknown 30개까지.

## 구현

`pipeline/scraper.py`
- `_score_post(p)` — 점수 공식 단일 함수.
- `_select_top_diverse(posts, max_posts, broadcast_dt, per_hour_cap, unknown_cap_ratio)`
  — 그리디 선택. broadcast_dt 미제공 시 wall-clock hour 로 fallback.
- `scrape_fmkorea()` 의 `unique_posts[:max_posts]` 를 `_select_top_diverse(...)`
  호출로 교체. 로그 메시지에 후보 수와 선별 방식 명시.

## 검증

`python experiments/b30_score_time_diversity.py` — 7/7 PASS
1. 점수 공식 정확성 (None/누락 0 처리 포함)
2. 한 시간대 cap=6 위반 없음 (30개 hot 후보 → 6개만)
3. bin 내 점수 내림차순 우선
4. 3개 시간대 (hour 0/+1/-1) 각각 cap 6 채워짐 → 18개 분산
5. unknown timestamp 글 → cap 30 (max_posts*0.25) 이내
6. broadcast_dt=None → wall-clock hour 기반 fallback
7. 후보 < max_posts → 가용 글 모두 반환

회귀:
- `experiments/b27_fmkorea_chromium.py` 6/6 PASS
- `experiments/test_manual_community_override.py` PASS

## 운영 메모

- `pipeline_config.json` 에 `fmkorea_max_pages=20`, `fmkorea_max_posts=120`
  반영 (로컬, gitignore).
- 페이지 20개 × 8~12초 = 키워드당 ~3~4분. chromium 백엔드와 결합 시
  키워드 1개 기준 총 수집 시간 ~3~5분. 전체 파이프라인 5h 대비 무시.
- per_hour_cap 은 현재 코드 상수 (6). 추후 운영 데이터 보고 config 화 검토.
- 점수 가중치(10/5)도 운영 후 community 매칭 hot_segments 결과로 튜닝 가능.
