# 2026-04-15-a4-closeout-hygiene — Closeout

A4 close-ack `OBJECT` verdict 후속으로 연 plan-only 세션. A4 산출물(결과 MD/YAML)과
측정 시점 anchor 소스(5 파일)의 provenance 비대칭 문제를 분리 진단하고, freeze 실행을
별도 후속 세션으로 분리한 채 `converged` 로 종료했다.

- 세션 ID: `2026-04-15-a4-closeout-hygiene`
- 상태: `converged` (planning-only; freeze 실행은 별도 세션)
- 턴: 5 (claude-code / codex / claude-code / codex / claude-code)
- Contract: C1 FAIL-then-PASS, C2 PASS, C3 PASS, C4 FAIL-then-PASS, C5 PASS

## Outcome

- Canonical artifact-freeze SHA = `c6b0adc` ("Add DAD artifacts and A1-A4 experiment
  closeout"). `0c078ea` 는 README-only sibling (`git merge-base` = `b62ada1`) 로 확정.
- G3 잔여 gap 은 5 파일 measurement anchor set (`pipeline/config.py`, `pipeline/main.py`,
  `pipeline/chunker.py`, `pipeline/claude_cli.py`, `pipeline/summarizer.py`) 뿐.
- 후속 freeze 세션에서 codex/a4-closeout-freeze 브랜치를 `c6b0adc` 에서 컷한 뒤
  commit 1 (5 anchors), commit 2 (hygiene session dir + root `Document/dialogue/state.json`,
  9-file show-stat) 로 랜딩 → 정확히 7 status entries 제거 예정.
- commit 3 (sha256 manifest) 는 기본값 deferred. G3 는 OR 이므로 freeze SHA 단독으로
  충족.

## Artifacts

- `provenance-boundary.md` — Option B 바운더리 맵. 24 live status entries 를
  G-A4-ANCHOR (5) / G-HYGIENE-SESSION (2 entries: root state + collapsed session dir) /
  G-UNRELATED-DIRTY (17) 로 분류. G-A4-ARTIFACT + G-DAD-SCAFFOLD + G-A1..A3-ARTIFACT 는
  `c6b0adc` 에서 이미 커버.
- `freeze-plan.md` — Option C 3-commit 슬라이스. §1 "왜 main 이 freeze base 가 아닌가"
  근거, §5 before (16 M + 8 ??) / after (10 M + 7 ??) 스냅샷 + 7-entry diff, §7 Turn 5
  resolutions (canonical SHA / 브랜치 base / commit-3 deferral).
- Turn packets 01–05 + `state.json` mirror + `summary.md`.

## Blockers resolved

- Turn 3 status-entry vs expanded-file 카운트 혼용 (15/12 오류) → Turn 5 에서 live
  16 M + 8 ?? 로 정정. `provenance-boundary.md §0 "Counting convention"` 에 1급
  규약으로 명문화.
- `Document/dialogue/state.json` 누락 → §2.1 row + §3 G3 coverage + §5 스냅샷 + commit 2
  allowlist 에 추가.
- Commit 3 애매성 → 기본 defer, ACK 가 명시 요구할 때만 재도입.
- 브랜치 base 애매성 → `main` 명시 제외 (replay risk + 세 번째 동명 병렬 commit risk).

## Open follow-ups (본 세션 밖)

- **A4 freeze-execute 세션** (suggested id: `2026-04-15-a4-freeze-execute`): `c6b0adc` 에서
  codex/a4-closeout-freeze 를 컷해 commit 1 + 2 를 실행하고, G5 = 정확히 7 entries
  cleaned 를 검증한 뒤 close-ack ACK verdict 를 발행한다.
- **Unrelated-dirty cleanup 세션**: `.gitignore` 에서 `experiments/_a4_run_*.txt`,
  `experiments/a3_measure.log`, `experiments/parser_test_output.txt`,
  `experiments/results/run.log` 커버 여부 + 9 non-anchor modified pipeline + 2
  untracked pipeline 파일 triage.
- **A4b methodology 세션**: start-offset 다각화 + 장르축 확보. freeze 위생과 독립.
- **`transcribe.py -c copy` 버그 수정 세션**: A4 해석과 독립, 파이프라인 신뢰성 이슈.
