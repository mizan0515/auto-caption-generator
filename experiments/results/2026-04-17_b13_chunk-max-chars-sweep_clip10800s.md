# B13 — chunk_max_chars 최적화 sweep

- 생성: 2026-04-17T11:53:38
- VOD: `12702452` (limit=10800s, duration=10800s)
- SRT: `12702452_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶_144p_clip10800s.srt`, overlap=30s
- 채팅: 2,285건 → 하이라이트 10개

## Filter OFF (raw cues)
- cues=986, total_chars=75,585

| chunk_max_chars | chunks | chars(평균/최대) | 분(평균/최대) | timeout risk |
|---:|---:|---|---|---|
| 15,000 | 6 | 12,771 / 14,999 | 30.6 / 38.8 | low |
| 20,000 | 4 | 19,044 / 19,974 | 45.5 / 50.4 | low |
| 30,000 | 3 | 25,309 / 29,964 | 60.4 / 72.7 | medium |
| 50,000 | 2 | 37,865 / 49,974 | 90.3 / 116.0 | high |

## Filter ON (B12 추천: radius=180s, cold=60s)
- cues=298, total_chars=22,401

| chunk_max_chars | chunks | chars(평균/최대) | 분(평균/최대) | timeout risk |
|---:|---:|---|---|---|
| 15,000 | 2 | 11,200 / 14,983 | 89.4 / 102.4 | low |
| 20,000 | 2 | 11,200 / 19,942 | 89.4 / 144.3 | low |
| 30,000 | 1 | 22,401 / 22,401 | 179.3 / 179.3 | medium |
| 50,000 | 1 | 22,401 / 22,401 | 179.3 / 179.3 | medium |

## 추천
- filter ON 그리드에서 timeout 위험 medium 이하 + 청크 수 최소: `chunk_max_chars=15,000` (chunks=2, max=14,983 chars, risk=low)

## 해석 가이드
- timeout_risk 는 chars_max 기준 휴리스틱 (한국어 ~1.6 chars/token, claude_timeout_sec=300).
- 실제 Haiku/Sonnet 호출 검증은 후속 (cost 우려로 sweep 단계 제외).
- 30분 클립은 total_chars 가 작아 chunk_max_chars 영향 미미. 풀 VOD 검증 권장.
