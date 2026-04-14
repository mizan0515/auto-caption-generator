# 2026-04-15-phase-a3-token-margin-sampling — Closeout

Phase A3는 Turn 6 codex 독립 재검증까지 완료하고 `converged` 로 종료했다.

- 측정 스코프:
  - `work/12702452/*clip1800s.srt`
  - `work/12702452/12702452_chat.log`
  - 30분 Korean talk / high-density chat
- 최종 권고:
  - `recommended_margin = 3.35x`
  - 단, **30분 Korean talk** 에 한정된 scoped recommendation
- 독립 재검산:
  - raw JSON 기준 `median=3.1541`, `P95=3.1843`, `recommended_margin=3.35`
  - 5/5 chunks consistency PASS
  - additive overhead는 A3-only mean `7,505.6`, A2 포함 mean `7,578.7`, std `211.5`
- 해석:
  - A2의 `1.80x` 는 특수해였고, A3는 ratio보다 additive overhead `~7.5k` 가 더 안정적인 설명임을 보여줌
- 미해결:
  - 길이/장르/밀도 일반화는 A3b/A4에서 별도 샘플 확보 후 재측정 필요
  - codex-side Claude auth는 Turn 6에서도 401 지속

이번 세션은 code/config/result 숫자를 바꾸지 않고 raw artifact 검증만으로 닫혔다.
