# 2026-04-27 B33 사용자 스킵 액션 (대시보드 우클릭)

## 배경

처리 시작된 VOD 를 도중에 스킵할 방법이 없었다. 잘못 트리거되거나 길이가
긴 (5h+) VOD 가 운영 우선순위에서 밀릴 때, 사용자가 직접 대시보드에서
끊을 수 있는 경로 필요.

옵션 검토:
- subprocess 격리 + kill: 큰 리팩터, 후보 1순위는 아님
- 협력적 cancel + stage 경계 체크: 작은 변경으로 즉시 효과. **선택**

## 결정

- terminal status `skipped_user` 신설 (`completed`, `skipped_bootstrap` 옆)
- state 에 `skip_requested` 플래그 — 진행 중 VOD 의 협력적 cancel 신호
- `process_vod()` 가 6개 stage 경계 (`start`, `analyzing`, `transcribing`,
  `chunking`, `summarizing`, `saving`) 와 Whisper batch 경계에서 플래그 확인
- 플래그 발견 시 `SkipRequested` 예외 → 외부 핸들러가 `mark_skipped_user`
  + work_dir 정리
- 비-진행 VOD (대기/error/pending_retry) 는 대시보드에서 즉시 `skipped_user`
  마킹 + work_dir rmtree

## 구현

`pipeline/state.py`
- `class SkipRequested(Exception)` — `video_no`, `channel_id`, `reason`
- `request_skip(video_no, channel_id)` → bool. 플래그만 설정
- `is_skip_requested(...)` → 디스크 reload 후 플래그 조회 (외부 변경 즉시 반영)
- `clear_skip(...)` — 플래그 해제
- `mark_skipped_user(...)` — terminal 전환 + 플래그 정리. terminal 보호 적용
- `_TERMINAL_STATUSES` 에 `"skipped_user"` 추가

`pipeline/main.py`
- `_raise_if_skip(state, vod, stage)` 헬퍼 — 플래그 시 `SkipRequested` raise
- `process_vod()` 의 6개 stage 전환 직전에 호출
- Whisper 호출 시 `cancel_check=lambda: state.is_skip_requested(...)` 전달
- `RuntimeError("cancelled")` → `SkipRequested` 변환
- `except SkipRequested` 핸들러 — `mark_skipped_user` + `_cleanup_work_dir`

`pipeline/transcriber.py`
- `transcribe_video(..., cancel_check=None)` — 새 파라미터
- watchdog 루프 (10s polling) 에서 `cancel_check()` 호출
- True 반환 시 `stop_event.set()` → transcribe.py 의 batch 루프가 다음 batch
  경계에서 break (line 605, 기존 메커니즘)
- worker 종료 후 `stop_event.is_set()` 이면 `RuntimeError("cancelled")` raise

`pipeline/monitor.py`
- 새 VOD 후보 제외 셋에 `skipped_user` 추가 — 폴링 시 이 status 는 다시 안 잡힘

`pipeline/dashboard.py`
- `_STATUS_LABELS` 에 `"skipped_bootstrap": "스킵 (bootstrap)"`,
  `"skipped_user": "스킵 (사용자)"` 추가
- 우클릭 메뉴에 "스킵 (영구 제외 + work dir 정리)" 항목 — terminal status 가
  아닐 때만 노출
- `_action_skip(key, status)`:
  - active (collecting/transcribing/...): 확인 다이얼로그 → `request_skip()`
    플래그만 설정. work_dir 정리는 process_vod 가 담당
  - 비-active (대기/error/pending_retry): 즉시 `mark_skipped_user` + rmtree

## 검증

`python experiments/b33_skip_action.py` — 9/9 PASS
1. request_skip → 플래그 설정 + is_skip_requested True
2. 없는 엔트리 → False
3. clear_skip → 플래그 해제
4. mark_skipped_user → terminal + 플래그 정리
5. monitor 가 `skipped_user` 도 새 VOD 후보 제외 (코드 검사)
6. skipped_user → retry / zombie 회수 대상 제외
7. terminal 보호 — 비-terminal update 가 클로버하지 못함
8. `_raise_if_skip` stage 경계에서 SkipRequested raise
9. 디스크 round-trip 보존 (status, skip_reason, skip_requested 정리)

회귀:
- B27 6/6 (chromium 백엔드)
- B30/B32 11/11 (선별 로직)
- B31 9/9 (timestamp 파서)
- manual override

## 한계

- Whisper batch 경계에서 cancel — 한 batch 가 끝나야 멈춤. batch_size=4 청크,
  청크당 ~10~30초 → 최대 ~2분 대기. 사용자에겐 다이얼로그로 미리 안내.
- Python thread 강제 종료 불가 — Whisper worker thread 는 `daemon=True` 로
  설정돼 프로세스 종료 시 정리됨. cancel 후 같은 프로세스 내에서는 background
  로 자연 종료될 때까지 진행 (CPU/메모리 일시 점유). 운영 영향은 작다.
- 즉시 kill 이 필요한 케이스: 데몬 일시정지/종료 후 work_dir 수동 삭제 + state
  엔트리 직접 편집. 대시보드 "상태에서 제거" + "오류 일괄 제거" 와 함께 사용.

## 운영 메모

- 대시보드 → "현재 상태" 탭 → 트리뷰 우클릭 → "스킵". 진행 중인 VOD 도 같은
  메뉴에서 처리.
- 진행 중 스킵: 다이얼로그에서 "Whisper batch 경계까지 최대 수 분" 안내.
- 스킵된 VOD 는 추후 재처리 원하면 "상태에서 제거" 후 monitor 가 다시 잡거나,
  "재처리" 메뉴로 강제 실행.
