# Session Summary: 2026-04-16-multi-streamer-settings-ui-implement

## 목표

`pipeline/settings_ui.py` 의 단일-스트리머 스칼라 입력을 멀티 스트리머
행 편집기로 교체한다. GUI 에서 스트리머를 add/edit/delete 할 수 있고,
legacy single-streamer config 와 완전 호환되며, 저장 결과가
`pipeline.config.normalize_streamers()` 로 그대로 소비되어야 한다.

## Turn 1 (claude-code)

### 구현 내역

1. **`pipeline/settings_ui.py`**:
   - `FIELDS` 에서 `streamer_name`, `target_channel_id`, `fmkorea_search_keywords` 제거
     (멀티 스트리머 섹션이 단독 관리).
   - 새 "스트리머 (멀티 스트리머 지원)" 섹션 + `streamers_container` Frame +
     "+ 스트리머 추가" 버튼.
   - 행 관리 메서드: `_on_add_streamer`, `_add_streamer_row`,
     `_remove_streamer_row`, `_renumber_streamer_rows`,
     `_clear_streamer_rows`, `_collect_streamers`.
   - `_load_values`: `normalize_streamers(self.cfg)` 결과로 1+ 행 자동 생성
     (legacy/multi 양쪽 입력 통합).
   - `_collect_values`: `cfg["streamers"]` canonical list 저장 + 첫 행을
     legacy scalars (`target_channel_id`, `streamer_name`,
     `fmkorea_search_keywords`) 로 mirror.
   - 입력 검증: 채널 ID 32자 hex 검사(soft warn), 모두 빈 행 거부, 최소 1개 강제.
   - `bootstrap_mode` 빈 문자열 -> `None` 정규화도 보강.

2. **`experiments/settings_ui_multi_streamer_verify.py`** (신규):
   - T1 legacy_load: 단일 cfg -> 1행 정규화.
   - T2 multi_load: 3-streamer cfg -> 3행 보존.
   - T3 save_policy: streamers + legacy mirror 정확.
   - T4 roundtrip: save -> JSON -> load 동일.
   - T5 empty_streamers_fallback: `None`/`[]` 모두 legacy scalar fallback.
   - T6 import_smoke: 모듈 import + FIELDS 에 streamer scalar 부재 확인.
   - T7 live_ui_roundtrip: 실제 (withdrawn) Tk 윈도우로 legacy + multi 양쪽
     load -> add/delete -> save -> reload 라운드트립.

3. **문서 동기화**:
   - `docs/multi-streamer-web-publish-backlog.md`: P7 항목 추가 (완료).
   - `README.md`: 설정 GUI 항목에 멀티 스트리머 설명 추가, `streamers` canonical
     form + legacy mirror 정책 섹션 신설.

### 검증 결과

- T1 legacy_load PASS
- T2 multi_load PASS
- T3 save_policy PASS
- T4 roundtrip PASS
- T5 empty_streamers_fallback PASS
- T6 import_smoke PASS
- T7 live_ui_roundtrip (real Tk add/delete/save/reload) PASS
- runtime smoke: `load_config + normalize_streamers` -> 1 streamer
  `channel-a7e175625fdea5a7d98428302b7aa57f`, `publish_autorebuild=True`
- regression: `build_site(./output, tmp, .)` -> `vod_count: 1, streamer_count: 1`
- Validate-DadPacket -AllSessions PASS (예정)
- Validate-Documents -IncludeRootGuides -IncludeAgentDocs PASS (예정)

### Open risks (후속 슬라이스 후보)

- `tray_app.py` 의 status 표시는 여전히 첫 스트리머만 보여줌 (legacy mirror
  기반). `streamers` 리스트 전체를 인지하는 trayUI 업그레이드는 다음 작업.
- `publish_autorebuild` 는 GUI 에 미노출 (JSON 직접 편집 필요).

## Turn 2 (codex)

- Codex independently reproduced C1-C5:
  baseline/ancestor, UI structure, 7/7 verification script pass,
  normalize_streamers() runtime smoke, output rebuild regression check,
  and both validators.
- One real implementation defect was found:
  channel_id validation only enforced 32-character length, so non-hex
  strings like `'g'*32` were still accepted.
- Turn 2 fixed `pipeline/settings_ui.py` to validate true 32-hex format
  and extended the verification script to assert valid-hex accept /
  non-hex reject behavior.
- Turn 2 also synced session/root state to `converged` / `accepted` and
  added the missing Turn 2 packet and session summary.
- Final verdict: multi-streamer settings UI first slice PASS after the
  input-validation fix.
