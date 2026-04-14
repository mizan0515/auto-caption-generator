# Chunk Size Experiment Results

- VOD: `12702452` / 제한 1800초
- SRT: 12702452_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶_144p_clip1800s.srt
- 실행 시각: 2026-04-14T16:27:06.208132

## 비교표

| 구성 | 청크수 | 타임라인 | 분당 밀도 | 하이라이트 | 요약자수 | 총 소요 |
|---|---|---|---|---|---|---|
| baseline_150k | 1 | 10 | 0.33/분 | 4 | 4,366 | 174.6s |
| chunk_15k | 1 | 14 | 0.47/분 | 4 | 4,063 | 152.5s |
| chunk_8k | 2 | 13 | 0.43/분 | 3 | 3,908 | 219.0s |
| chunk_5k | 3 | 20 | 0.67/분 | 3 | 4,976 | 245.7s |

## 전체 메트릭 (JSON)

```json
[
  {
    "label": "baseline_150k",
    "max_chars": 150000,
    "overlap_sec": 45,
    "chunk_count": 1,
    "total_chunk_chars": 8446,
    "summary_chars": 4366,
    "timeline_entries": 10,
    "highlight_entries": 4,
    "entries_per_min": 0.33,
    "chunk_phase_sec": 98.1,
    "merge_phase_sec": 76.5,
    "total_sec": 174.6,
    "output_path": "C:\\github\\auto-caption-generator\\experiments\\results\\baseline_150k_20260414_161648.md",
    "has_hashtags": true,
    "has_pullquote": true,
    "has_editor_notes": true,
    "char_count": 4366,
    "line_count": 99
  },
  {
    "label": "chunk_15k",
    "max_chars": 15000,
    "overlap_sec": 30,
    "chunk_count": 1,
    "total_chunk_chars": 8446,
    "summary_chars": 4063,
    "timeline_entries": 14,
    "highlight_entries": 4,
    "entries_per_min": 0.47,
    "chunk_phase_sec": 71.5,
    "merge_phase_sec": 81.0,
    "total_sec": 152.5,
    "output_path": "C:\\github\\auto-caption-generator\\experiments\\results\\chunk_15k_20260414_161921.md",
    "has_hashtags": true,
    "has_pullquote": true,
    "has_editor_notes": true,
    "char_count": 4063,
    "line_count": 83
  },
  {
    "label": "chunk_8k",
    "max_chars": 8000,
    "overlap_sec": 30,
    "chunk_count": 2,
    "total_chunk_chars": 8619,
    "summary_chars": 3908,
    "timeline_entries": 13,
    "highlight_entries": 3,
    "entries_per_min": 0.43,
    "chunk_phase_sec": 95.4,
    "merge_phase_sec": 123.6,
    "total_sec": 219.0,
    "output_path": "C:\\github\\auto-caption-generator\\experiments\\results\\chunk_8k_20260414_162300.md",
    "has_hashtags": true,
    "has_pullquote": true,
    "has_editor_notes": true,
    "char_count": 3908,
    "line_count": 78
  },
  {
    "label": "chunk_5k",
    "max_chars": 5000,
    "overlap_sec": 20,
    "chunk_count": 3,
    "total_chunk_chars": 8593,
    "summary_chars": 4976,
    "timeline_entries": 20,
    "highlight_entries": 3,
    "entries_per_min": 0.67,
    "chunk_phase_sec": 108.5,
    "merge_phase_sec": 137.2,
    "total_sec": 245.7,
    "output_path": "C:\\github\\auto-caption-generator\\experiments\\results\\chunk_5k_20260414_162706.md",
    "has_hashtags": true,
    "has_pullquote": true,
    "has_editor_notes": true,
    "char_count": 4976,
    "line_count": 106
  }
]
```
