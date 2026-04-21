# Phase C — 스트리머별 lexicon + 사후 교정 시스템

날짜: 2026-04-21
대상: `pipeline/lexicon.py` (신규), `scripts/recorrect_reports.py` (신규), 그리고 `transcribe.py` / `pipeline/transcriber.py` / `pipeline/main.py` / `pipeline/summarizer.py` / `pipeline/claude_cli.py` / `pipeline/config.py` / `prompts/청크 통합 프롬프트.md` 통합 변경.

## 1. 문제

Whisper STT 가 채널 고유 표기(스트리머 별명·LoL 챔피언·신조어)를 자주 오인식했고, 이미 배포된 16개 리포트에 누적된 오타가 시청자 가독성을 해쳤다. 채팅·커뮤니티에는 정답 표기가 풍부하지만 파이프라인이 활용하지 않았다.

## 2. 해결책 — 4중 방어선

| # | 단계 | 메커니즘 |
|---|------|---------|
| 1 | Whisper STT | `pipeline/lexicon.build_lexicon()` 가 채팅·커뮤니티·VOD 제목·나무위키에서 상위 30 토큰 추출 → `format_for_whisper()` → `transcribe.run_caption_generation(initial_prompt_text=...)` 로 prompt bias |
| 2 | Claude 청크 요약 | `pipeline/summarizer.process_chunks(lexicon_terms=...)` + `CHUNK_SYSTEM_PROMPT` 의 "사전 발음 유사 표기는 사전 표기로 교정" 지시 |
| 3 | Claude 통합 요약 | `prompts/청크 통합 프롬프트.md` Constraint — 채팅/커뮤니티 표기를 ground-truth |
| 4 | 사후 교정 | `python -m scripts.recorrect_reports` — 이미 만든 MD 도 사전 + Claude 매핑으로 재교정, `.md.bak` 백업 |

## 3. 측정값

### Lexicon 노이즈 필터링 효과
스톱워드 47개 → 약 130개로 확장 + 영문 case-fold dedup 후, 채널 a7e175... 의 상위 30 토큰:

- proper-noun 비율: 약 27/30 (탬탬버린 / lck / 미드 / 바텀 / 정글 / 원딜 / 서폿 / 베인 / 카르마 / 이즈 / 아지르 / 티원 / 제이스 / 탬하 등)
- 잔존 노이즈: 좋음 / 개웃기네 / 저게 (3/30) — 향후 보강

### 사후 교정 결과 (16 VOD)

7개 VOD 에서 실제 오타 발견·교정:

| VOD | 매핑 |
|-----|------|
| 12408646 | 템템이 → 탬탬이 |
| 12447875 | 삐구 → 삐부, 따윤희 → 따효니 |
| 12560727 | 피부님 → 삐부님 |
| 12568235 | 애니 서포트 → 애니 서폿 |
| 12670366 | 명호 → 명훈 |
| 12686305 | 섬브라/손브라 → 솜브라 |
| 12702452 | 돌복이 → 똘복이 |

### 속도 최적화

| 버전 | 1 VOD 호출 시간 | 16 VOD 일괄 |
|------|---------------|------------|
| v1: Claude 가 전체 MD 재출력 | ~3 분 | ~50 분 |
| v2: Claude 가 매핑 JSON 만 출력 + Python find-replace | ~50 초 | ~13 분 |
| v3: 이미 교정된 VOD 스킵 (`.md.bak` 존재 검사) | 0.002 초 | 즉시 (변경 없는 경우) |

비용도 출력 토큰 ~100 배↓ → API 비용 ~50 배↓.

## 4. 신뢰성 보강 (인프라)

- **Claude CLI JSON `result:""` 버그**: `pipeline/claude_cli.py` 의 `_parse_claude_output()` 가 `_EmptyJsonResult` 표식 → `_call_claude_cli()` 가 자동으로 `--output-format text` 모드 재호출. 메인 파이프라인 요약 실패 위험 제거.
- **Rate-limit**: 메인은 기존 `@retry(max_retries=2, backoff_base=30s)`, recorrect 도 자체 지수 백오프.
- **Lexicon 자동 무효화**: 7일 TTL 안이라도 `work/<vod>/*_chat.log.json` mtime 이 캐시 빌드 후면 자동 재빌드 → 신조어 누락 갭 제거.
- **Config validator**: `lexicon_limit` / `lexicon_cache_ttl_hours` 가 `pipeline/config._INT_FIELDS` 에 등록 → 잘못된 값으로 Whisper 30 분 돌리고 죽는 UX 차단.
- **회귀 테스트**: `experiments/test_recorrect_apply.py` 가 `_parse_replacements` / `_apply_replacements` 의 9 케이스 검증 (코드펜스, 빈 리스트, identity skip, 매치 0 등).

## 5. 노출된 CLI

```
python -m scripts.recorrect_reports                       # 신규 .md.bak 없는 VOD 만
python -m scripts.recorrect_reports --force               # 모든 VOD 강제 재호출
python -m scripts.recorrect_reports --rebuild-lexicon     # lexicon 캐시 무효 + 강제 재호출
python -m scripts.recorrect_reports --video-no 12568235   # 특정 VOD
python -m scripts.recorrect_reports --dry-run             # diff 만 표시
python -m scripts.recorrect_reports --no-publish          # 교정만, refresh_reports 스킵
```

## 6. 한 줄 요약

**스트리머별 사전 + 4중 방어 + JSON 매핑 기반 사후 교정으로, Whisper 고유명사 오인식 → 시청자 가시 오타 갭을 닫았다. 16 VOD 중 7건 실제 교정·배포 완료.**
