# 자동 퍼블리시 훅 — 구현 상태

세션 `2026-04-16-multi-streamer-web-publish-mvp` Turn 1 에서 계획.
세션 `2026-04-16-auto-publish-hook-implement` Turn 1 에서 구현.

## 현재 상태

- `publish/hook.py` (`auto_publish_after_vod()`) — VOD 처리 성공 후 자동 site rebuild.
- `pipeline/main.py` (`_try_auto_publish()`) — `process_vod()` 의 두 성공 경로(일반 + 빈 SRT)에서 호출.
- `pipeline_config.json` 의 `publish_autorebuild` (기본값 `true`) 로 활성/비활성 제어.

## 삽입 지점

`pipeline/main.py::process_vod()` 의 두 success path:
1. 일반 완료 — 리포트 저장 후, 임시 파일 정리 전.
2. 빈 SRT 완료 — 최소 리포트 저장 후, return 전.

에러 경로에서는 호출되지 않음 (AST 검증 완료).

## 안전 보장

1. `publish_autorebuild` 플래그 — `false` 면 무조건 스킵.
2. 이번 VOD 산출물 검증 — md, html, metadata.json 세 파일이 모두 있어야 진행.
3. output 디렉토리 전체 검증 — 최소 1세트의 완전한 VOD 산출물(md+html+metadata) 필요.
4. 예외 차단 — `_try_auto_publish()` + `rebuild_site_safe()` 이중 try/except 로 pipeline 실패 격리.
5. state 기록 — 성공 시 `publish_status=success`, 실패/스킵 시 `publish_status=skipped_or_failed`.

## 비활성화 / 롤백

1. `pipeline_config.json` 의 `publish_autorebuild` 를 `false` 로 설정.
2. 수동 빌드는 여전히 `python -m publish.hook` 또는 `python -m publish.builder.build_site` 로 가능.

## 미구현 (후속 슬라이스)

- Cloudflare Pages 자동 업로드 (`wrangler pages deploy site`).
- 증분 빌드 (mtime 기반 skip).
- daemon 장기 운영에서의 rebuild frequency control.
- GUI 설정 UI 에 `publish_autorebuild` 항목 추가.
