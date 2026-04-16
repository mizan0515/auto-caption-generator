# Session Summary — 2026-04-16-multi-streamer-web-publish-mvp

- **Status:** converged (Turn 1 seals Slice 1).
- **Mode:** hybrid, scope=medium, max_turns=5, current_turn=1.
- **Last agent:** claude-code.

## What this session delivered

"멀티 스트리머 + 무료 웹 퍼블리시 MVP" 의 첫 번째 vertical slice. runtime 파이프라인을 건드리지 않고 publish-view 레이어만으로 (a) 멀티 스트리머-ready 데이터 모델, (b) 결정론적 정적 사이트 빌더, (c) 4화면 정적 웹 MVP (목록/상세/검색), (d) 무료 호스팅 가이드, (e) 자동 퍼블리시 훅 계획서를 완결.

## Key Artifacts

- `docs/multi-streamer-web-publish-backlog.md` — P0~P6 백로그 (본 세션 = Slice 1).
- `docs/publish-schema.md` — VodRecord 필드 + backward compat 파생 규칙 + 사이트 디렉토리 구조.
- `docs/deploy-free-hosting.md` — Cloudflare Pages 1순위 / GitHub Pages 2순위 + 배포 전 체크리스트.
- `docs/auto-publish-hook-plan.md` — Slice 2 삽입 지점 3후보 + 롤백 프로토콜.
- `publish/builder/build_site.py` — output/ → site/ 결정론적 빌더 (CLI).
- `publish/hook.py` (`rebuild_site_safe()`) — pipeline 에 안전 호출용 thin wrapper (아직 미삽입).
- `publish/web/{index,streamer,vod,search}.html + assets/{app.css,app.js}` — 정적 웹 MVP.
- `README.md` — "웹 퍼블리시 (멀티 스트리머 MVP)" 섹션 추가.
- `.gitignore` — `site/` 추가 (빌드 산출물 미추적).

## Verification

- `python -m publish.builder.build_site` → `{vod_count: 1, streamer_count: 1, assets_copied: 6 files, site_dir: ...}`.
- `find site -maxdepth 4 -type f` → 14 files (index.html/streamer.html/vod.html/search.html + assets/{app.css,app.js} + index.json + streamers.json + search-index.json + streamers/channel-*/index.json + vods/11688000/{index.json, report.html, report.md, metadata.json}).
- `diff -q output/*.{md,html} vs site/vods/11688000/report.*` + metadata.json → ALL IDENTICAL.
- `python -m http.server --directory site 8765` + curl 7회 → 7/7 HTTP 200.
- Client-side substring 검색 5쿼리: 올림픽=1 / 탬탬=1 / 스노보드=1 / 에어컨=1 / nothing-should-match=0.
- `rg "NID_AUT|NID_SES" site/` → 0 matches.
- `python -m publish.hook` → 빌더와 동일 JSON.

## Safety Invariants (C5)

- Runtime pipeline 코드 무변경 (pipeline/, content/, transcribe.py, tray_app.py, pipeline_config.json 전부 무수정).
- Remote mutation / push / PR 생성 없음.
- A4 결과 (2026-04-15 / 2026-04-16) overwrite 없음.
- live worktree write 없음 (모든 편집은 auto-caption-generator-main sister 에서).
- Chzzk 쿠키 노출 없음.

## Open Risks (next sessions)

- 자동 퍼블리시 hook 의 남은 통합 리스크. docs/auto-publish-hook-plan.md 의 3 후보 지점. Slice 2.
- Multi-streamer ingestion 이 실사용 검증 전 (현재 데이터는 단일 스트리머 1건). 두 번째 스트리머 실 run 필요.
- A4 chunk_max_tokens promotion 은 cache-TTL-aware retry protocol 세션으로 분리 (backlog P6).

## Decisions

- publish/ 레이어는 runtime 권위에 종속되지 않는 **derived view** 로 설계한다. 누락 필드는 빌더가 파생하고, metadata JSON 자체는 건드리지 않는다.
- 평면 `site/vods/<video_no>/` 경로를 채택. 스트리머 간 video_no 충돌은 실제로 관찰될 때 Slice 2 에서 경로를 streamer-prefixed 로 옮긴다.
- 검색은 Slice 1 에서는 `site/search-index.json` 에 대한 client-side substring. 형태소/n-gram 업그레이드는 backlog P3.
- 무료 호스팅 1순위는 Cloudflare Pages Direct Upload (repo push 없이 site/ 드롭). GitHub Pages 는 public repo 요구 + 방송 콘텐츠 노출 고려로 2순위.

## Closure

handoff.suggest_done=true, done_reason 기록. 본 세션 = `converged`. 다음 세션은 backlog P3/P4/P5/P6 중 사용자 우선순위에 따라 개별 세션으로 분기.
