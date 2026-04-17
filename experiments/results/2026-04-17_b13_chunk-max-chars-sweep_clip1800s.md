# B13 — chunk_max_chars 최적화 sweep

- 생성: 2026-04-17T11:53:38
- VOD: `12702452` (limit=1800s, duration=1800s)
- SRT: `12702452_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶_144p_clip1800s.srt`, overlap=30s
- 채팅: 2,285건 → 하이라이트 10개

## Filter OFF (raw cues)
- cues=211, total_chars=13,402

| chunk_max_chars | chunks | chars(평균/최대) | 분(평균/최대) | timeout risk |
|---:|---:|---|---|---|
| 15,000 | 1 | 13,402 / 13,402 | 30.1 / 30.1 | low |
| 20,000 | 1 | 13,402 / 13,402 | 30.1 / 30.1 | low |
| 30,000 | 1 | 13,402 / 13,402 | 30.1 / 30.1 | low |
| 50,000 | 1 | 13,402 / 13,402 | 30.1 / 30.1 | low |

## Filter ON (B12 추천: radius=180s, cold=60s)
- cues=185, total_chars=11,897

| chunk_max_chars | chunks | chars(평균/최대) | 분(평균/최대) | timeout risk |
|---:|---:|---|---|---|
| 15,000 | 1 | 11,897 / 11,897 | 30.1 / 30.1 | low |
| 20,000 | 1 | 11,897 / 11,897 | 30.1 / 30.1 | low |
| 30,000 | 1 | 11,897 / 11,897 | 30.1 / 30.1 | low |
| 50,000 | 1 | 11,897 / 11,897 | 30.1 / 30.1 | low |

## 추천
- filter ON 그리드에서 timeout 위험 medium 이하 + 청크 수 최소: `chunk_max_chars=15,000` (chunks=1, max=11,897 chars, risk=low)

## 해석 가이드
- timeout_risk 는 chars_max 기준 휴리스틱 (한국어 ~1.6 chars/token, claude_timeout_sec=300).
- 실제 Haiku/Sonnet 호출 검증은 후속 (cost 우려로 sweep 단계 제외).
- 30분 클립은 total_chars 가 작아 chunk_max_chars 영향 미미. 풀 VOD 검증 권장.
