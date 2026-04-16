# Publish Schema — Multi-Streamer Web MVP

세션: `2026-04-16-multi-streamer-web-publish-mvp` Turn 1
권위: 본 문서는 **publish-view** 의 권위다. runtime 레이어(`pipeline/`, `pipeline_config.json`)의 권위는 `PROJECT-RULES.md` source-of-truth 순서를 따른다.

## 설계 원칙

1. **런타임을 바꾸지 않는다.** 기존 `pipeline/` 과 `output/*.md/html/_metadata.json` 산출물을 깨뜨리지 않는다.
2. **빌더 레이어에서 파생한다.** 메타데이터에 없는 `streamer_id`, `search_text` 등은 빌더가 유도한다.
3. **멀티 스트리머-ready.** Slice 1 데이터는 단일 스트리머일 수 있지만, 스키마와 디렉토리 구조는 여러 스트리머를 가정한다.
4. **Free-hosting 친화적.** 모든 산출물은 정적 파일. JSON + HTML + 정적 에셋만.
5. **클라이언트-사이드 검색.** 서버 없이 검색 인덱스를 JSON 으로 번들.

## Single-Streamer Assumption Audit (Turn 1)

현재 파이프라인에 박혀있는 단일 스트리머 가정:

- `pipeline/config.py` DEFAULT_CONFIG: `target_channel_id` (단일), `streamer_name` (단일), `fmkorea_search_keywords` (단일 세트).
- `pipeline/models.py::VODInfo`: `channel_id`, `channel_name` 만 가진다. `streamer_id` 슬러그 없음.
- `pipeline/summarizer.py::generate_reports()`: 출력 파일명 `{video_no}_{date}_{title}.{md,html}` — 스트리머 prefix 없음. video_no 가 동일한 여러 스트리머는 충돌 위험.
- `pipeline/summarizer.py` metadata JSON 필드: `video_no, title, channel, duration, publish_date, category, total_chats, highlight_count, highlights, processed_at`. **없음**: `streamer_id`, `channel_id`, `platform`, `thumbnail_url`, `search_text`.
- `pipeline/state.py::PipelineState._data`: `processed_vods` 는 video_no → entry 의 단일 평면 맵. 스트리머 grouping 없음.

Slice 1 에서는 이 모든 것을 **파생 레이어**로만 보정했다. 이후 runtime 세션 `2026-04-16-multi-streamer-runtime-implement` 에서 다음이 변경됨:
- `pipeline_config.json` 에 `streamers` 리스트 필드 추가 (legacy 단일 스트리머 호환).
- `VODInfo` 에 `streamer_id` 필드 추가.
- `PipelineState` 에 composite key `{channel_id}:{video_no}` 지원.
- `generate_reports()` metadata JSON 에 `channel_id`, `streamer_id`, `platform`, `thumbnail_url` 필드 추가.
- `run_daemon()`, `run_once()` 가 스트리머 목록 순회.
- 빌더는 metadata `channel_id` 를 1차 권위로, pipeline_config 를 fallback 으로 사용.

## Publish 레코드 필드 (VOD 단위)

```json
{
  "streamer_id":        "channel-a7e175625fdea5a7d98428302b7aa57f",
  "streamer_name":      "탬탬버린",
  "channel_id":         "a7e175625fdea5a7d98428302b7aa57f",
  "platform":           "chzzk",
  "video_no":           "11688000",
  "title":              "밀라노 올림픽 스노보드 같이 보자아 ...",
  "published_at":       "2026-02-10T02:28:59+09:00",
  "published_date_str": "20260210",
  "duration_sec":       9463,
  "platform_category":  "동계 올림픽",
  "content_judgement":  null,
  "summary_md_path":    "vods/11688000/report.md",
  "summary_html_path":  "vods/11688000/report.html",
  "metadata_json_path": "vods/11688000/metadata.json",
  "thumbnail_url":      null,
  "search_text":        "탬탬버린 | 밀라노 올림픽 ... | 핵심 해시태그 | pull quote | 타임라인 제목 top N",
  "stats": {
    "total_chats":      1544,
    "highlight_count":  6
  },
  "processed_at":       "2026-04-16T05:23:58+09:00"
}
```

### 필드 도출 규칙 (backward compat)

| 필드                 | 기존 metadata에 있음 | 빌더 파생 방법 |
|----------------------|----------------------|----------------|
| `streamer_id`        | **있음** (runtime 세션 이후 metadata 에 직접 기록) | metadata `streamer_id` 가 권위. 없으면 `channel_id` 에서 `"channel-" + channel_id`. 둘 다 없으면 `"name-" + slug(channel_name)`. |
| `streamer_name`      | `channel` 필드에서 유도 | `metadata.channel` 또는 `pipeline_config.streamer_name`. |
| `channel_id`         | **있음** (runtime 세션 `2026-04-16-multi-streamer-runtime-implement` 이후 metadata 에 직접 기록) | metadata `channel_id` 가 권위. 없으면 `pipeline_config.target_channel_id` fallback (레거시). |
| `platform`           | 아니오               | 현재는 하드코딩 `"chzzk"`. 다른 플랫폼 추가 시 확장. |
| `published_at`       | `publish_date` (문자열) | ISO 변환 시도 → 실패하면 `"YYYY-MM-DD HH:MM:SS"` 로 유지. |
| `published_date_str` | 파일명에서 `_20260210_` | 파일명이 권위, 메타데이터 fallback. |
| `duration_sec`       | `duration`            | 그대로. |
| `platform_category`  | `category`            | 그대로. `""` 면 `null`. |
| `content_judgement`  | 아니오               | 현재 null. 향후 annotation 전용 필드. |
| `summary_md_path`    | 파일명으로 재구성     | 빌더가 `vods/<video_no>/report.md` 로 복사. |
| `summary_html_path`  | 파일명으로 재구성     | 빌더가 `vods/<video_no>/report.html` 로 복사. |
| `metadata_json_path` | 파일명으로 재구성     | 빌더가 `vods/<video_no>/metadata.json` 으로 복사. |
| `thumbnail_url`      | 아니오               | 현재 모든 source 에 없다. `VODInfo.thumbnail_url` 필드는 존재하지만 파이프라인이 채우지 않음. Slice 1 은 `null`. |
| `search_text`        | 아니오               | 빌더가 `streamer_name + title + hashtags + pull_quote + timeline titles` 로 조립. |
| `stats`              | 일부                  | `total_chats`, `highlight_count` 는 metadata 에서. 나머지는 빌더가 md 파싱. |
| `processed_at`       | 있음                  | 그대로. |

## 사이트 디렉토리 구조

```
site/
├── index.json                        # { "streamers": [...], "total_vods": N, "generated_at": "..." }
├── streamers.json                    # [{ streamer_id, streamer_name, vod_count }]
├── streamers/
│   └── <streamer_id>/
│       └── index.json                # { streamer, vods: [VOD summary rows] }
├── vods/
│   └── <video_no>/
│       ├── index.json                # 위의 VOD publish 레코드 full
│       ├── report.html               # 기존 generate_reports 산출 HTML 사본
│       ├── report.md                 # 기존 MD 사본 (클라이언트-사이드 렌더링 backup)
│       └── metadata.json             # 기존 metadata.json 사본
├── search-index.json                 # [{ video_no, streamer_id, title, search_text }]
├── assets/
│   ├── app.css
│   └── app.js
├── index.html                        # 스트리머 목록
├── streamer.html                     # 스트리머별 VOD 목록
├── vod.html                          # VOD 상세 (report.html 을 iframe 또는 inline)
└── search.html                       # 검색 UI
```

- `<streamer_id>` 는 안전한 slug 형태로 빌더가 정제한다.
- `<video_no>` 는 원본 그대로 (숫자 문자열).
- 스트리머 여러 명이 같은 `video_no` 를 쓸 수 있는 미래를 대비해 `site/vods/` 경로 대신 `site/streamers/<streamer_id>/vods/<video_no>/` 로 배치할 수도 있다. Slice 1 은 **단순함을 위해** 평면 `vods/` 를 쓰고, 충돌이 실제로 나오면 별도 세션에서 이전한다. 이 결정은 `docs/multi-streamer-web-publish-backlog.md` P4 승격 시 재평가.

## 검색 인덱스

```json
[
  {
    "video_no": "11688000",
    "streamer_id": "channel-a7e175625fdea5a7d98428302b7aa57f",
    "streamer_name": "탬탬버린",
    "title": "밀라노 올림픽 스노보드 같이 보자아 ...",
    "published_at": "2026-02-10T02:28:59+09:00",
    "search_text": "탬탬버린 | 밀라노 올림픽 스노보드 ... | #올림픽 #스노보드 ..."
  }
]
```

Slice 1 검색 = JS 가 `search-index.json` 을 fetch 해서 **대소문자 무시 substring** 매칭. 결과는 `vod.html?v=<video_no>` 로 링크. 업그레이드는 P3.
