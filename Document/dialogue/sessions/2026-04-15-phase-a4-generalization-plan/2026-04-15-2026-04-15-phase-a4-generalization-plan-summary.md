# 2026-04-15-phase-a4-generalization-plan — Closeout

Phase A4는 Turn 6 codex 독립 재검증과 Turn 7 closeout까지 완료하고 `converged` 로 종료했다.

- 측정 스코프:
  - `work/12702452/*clip1800s.srt` (W1, 30분)
  - `work/12702452/*clip3600s_*.srt` (W2, 1시간)
  - `work/12702452/*clip10800s_*.srt` (W3, 3시간)
  - `work/12702452/12702452_chat.log` (동일 VOD chat 2,285 msgs)
  - 단일 스트리머 Korean talk, 3개 길이 샘플
- 최종 권고:
  - decision = **`per_cell_multiplicative`**
  - per-cell margins: W1 `3.37x`, W2 `2.80x`, W3 `2.80x`
  - **global multiplicative promotion 차단**:
    - covered cells `3 < 5`
    - genres `1 < 2` (talk only)
    - W1 P95 `3.2008` outside global median P95 `2.6606` ±15% window `[2.2615, 3.0597]`
- 독립 재검산 (Turn 6 codex):
  - raw JSON 12 rows 전부 `consistency_pass=true`
  - per-cell aggregates: W1 median=2.6983 P95=3.2008 addΔ=7,514 / W2 median=2.4253 P95=2.6606 addΔ=7,604 / W3 ≡ W2
  - additive overhead range `[7,311, 7,817]`, median `7,620` (A3 ~7.5k 재현)
  - CLI cache 상수 `20,668` 12/12 cold calls
  - template_hash `4d732b40fa470862` (prefix SHA256[:16])
- 해석:
  - A3의 `3.35x`는 (30min, talk, high) 단일 샘플의 상한이었고, A4는 같은 축을 1h/3h로 확장한 결과 W1에서만 재현, W2/W3는 lower-density 환경에서 `2.80x`로 떨어짐
  - W2 ≡ W3는 same-start-offset content overlap의 산물이며 effective cell 수는 2개
  - additive `~7.5k` + CLI cache `20,668` constant는 A3와 동일하게 유지
- 미해결 (후속 슬라이스 후보):
  - genre-axis 확장 (game / reaction-or-music)
  - `transcribe.py` split_video bug fix (-c copy keyframe cut 시 part002 degenerate)
  - A4b start-offset diversification (W2/W3 duplicate 해소)
- runtime 변경:
  - `pipeline/config.py:26 chunk_max_tokens=None` **그대로 유지**
  - `pipeline/*`, `transcribe.py` 수정 없음
- codex-side auth:
  - Turn 2/4/6 모두 401 유지, claude-code가 Turn 5 execute 담당

이번 세션은 code/config/result 숫자를 바꾸지 않고 raw artifact 검증 + 체크포인트 PASS 확인으로 닫혔다.
