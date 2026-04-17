# Pipeline Improvement Backlog

최종 갱신: 2026-04-17. 이 문서는 자기 구동형 개발 프롬프트(`DEVELOP.md`)의 작업 목록이다.
각 항목은 독립적으로 구현/테스트 가능한 단위다.
완료 시 `[x]`로 표기하고 검증 결과를 한 줄로 기록한다.

## 우선순위 P0 — 토큰 효율 (즉시)

- [x] **B01 채팅 하이라이트 기반 자막 필터링**
  - 파일: `pipeline/chunker.py`, `pipeline/main.py`
  - 현상: 10시간 VOD의 자막 244,389자가 전부 Claude에 전송됨
  - 목표: 채팅 하이라이트 ±N분은 상세, 나머지는 30초당 1줄 샘플링
  - 파라미터: `highlight_radius_sec` (기본 300=5분), `cold_sample_sec` (기본 30)
  - 기대: 244K자 → ~100K자 (60% 절감), 호출 15회 → 6회
  - 검증: 실제 SRT + 채팅으로 필터 전후 크기 비교, 시간 커버리지 100% 확인
  - 주의: 필터링 후에도 전체 시간축이 빠짐없이 표현되어야 함 (cold 구간도 샘플 포함)

- [x] **B02 chunk prompt에서 내부 메트릭 제거**
  - 파일: `pipeline/summarizer.py`
  - 현상: merge 프롬프트에 "채팅수 {count}, 종합점수 {composite:.4f}" 포함
  - 문제: Claude 지시문이 "내부 메트릭 노출 금지"라고 하면서 프롬프트에서 메트릭을 주입
  - 목표: highlight 정보를 타임코드 + 설명적 표현으로 변환

- [x] **B03 전체 채팅 리스트 반복 필터링 제거**
  - 파일: `pipeline/main.py`, `pipeline/summarizer.py`
  - 현상: process_chunks()에 50K개 채팅 전체를 전달 → 매 청크마다 전체 스캔
  - 목표: main.py에서 청크별 채팅을 미리 슬라이싱하여 전달

## 우선순위 P1 — 안정성 (중요)

- [x] **B04 find_edit_points 에러 핸들링**
  - 파일: `pipeline/main.py:199`
  - 현상: 채팅 분석 실패 시 전체 파이프라인 크래시
  - 목표: try/except로 감싸고 빈 highlights로 fallback

- [x] **B05 Whisper 실행 타임아웃/에러 핸들링**
  - 파일: `pipeline/transcriber.py`
  - 현상: Whisper가 행(hang) 걸리면 무한 대기
  - 목표: 타임아웃 설정 + 에러 시 graceful 실패

- [ ] **B06 다운로더 bare pass 제거**
  - 파일: `pipeline/downloader.py:107-115`
  - 현상: 다운로드 실패를 조용히 무시, 불완전 파일 남김
  - 목표: 실패 시 파일 정리 + 명시적 에러 발생

- [ ] **B07 실패 VOD 재시도 시 스트리머별 설정 유실**
  - 파일: `pipeline/main.py:393`
  - 현상: 재시도 시 글로벌 cfg 사용 → 스트리머별 검색 키워드 무시
  - 목표: failed_vods에 channel_id 저장 → 재시도 시 해당 스트리머 cfg 복원

## 우선순위 P2 — 품질 (개선)

- [ ] **B08 SRT 반복 파싱 제거**
  - 파일: `pipeline/summarizer.py:197-212`
  - 현상: find_subtitle_peaks()와 build_community_signal()이 각각 parse_srt() 호출
  - 목표: cues를 한 번 파싱하고 두 함수에 전달

- [ ] **B09 HTML 파싱 fallback 강화**
  - 파일: `pipeline/summarizer.py:383-497`
  - 현상: Claude 출력이 예상 포맷에서 벗어나면 파싱 실패 → 빈 타임라인
  - 목표: 유연한 파싱 + 항상 raw_fallback 유지

- [ ] **B10 FM코리아 세션 재사용**
  - 파일: `pipeline/scraper.py:268-273`
  - 현상: 매 scrape마다 세션 생성 + 메인 페이지 방문
  - 목표: 데몬 모드에서 세션 재사용

- [ ] **B11 오래된 VOD FM코리아 자동 스킵**
  - 파일: `pipeline/main.py`, `pipeline/scraper.py`
  - 현상: 20일 전 VOD도 FM코리아 검색 시도 → 의미없는 네트워크 호출
  - 목표: VOD publish_date가 48시간 이전이면 fmkorea 스킵

## 우선순위 P3 — 실험/튜닝

- [ ] **B12 하이라이트 필터 파라미터 최적화 실험**
  - highlight_radius_sec: [180, 300, 420, 600]
  - cold_sample_sec: [15, 30, 60]
  - 측정: 필터 후 자수, 요약 품질 (타임라인 항목 수, 시간 커버리지), 호출 수
  - 기준: 전체 방송 시간의 80% 이상 타임라인에 표현되어야 함

- [ ] **B13 chunk_max_chars 최적화 실험**
  - 후보: [15000, 20000, 30000, 50000]
  - 측정: 타임아웃 발생 여부, 요약 밀도(항목/시간), 총 호출 수

## 완료 기록

| ID | 완료일 | 검증 | 비고 |
|----|--------|------|------|
| B01 | 2026-04-17 | ✅ 10h VOD: 377K→124K chars (67% 절감), 13→5 chunks, 시간커버리지 유지 | chunker.py + main.py + config.py |
| B02 | 2026-04-17 | ✅ Tier2: 메트릭 누출 0건, 순위→설명 변환 검증 | chat_analyzer.py + summarizer.py |
| B03 | 2026-04-17 | ✅ Tier2: bisect 슬라이싱 84x 속도향상 (5.07→0.06ms), edge case 통과 | summarizer.py |
| B04 | 2026-04-17 | ✅ Tier2: KeyError 크래시 확인 후 try/except 보호 | main.py |
| B05 | 2026-04-17 | ✅ Tier2: stall/overall timeout/pre-progress 3 시나리오 watchdog 검증 | transcriber.py + main.py + config.py |
| — | — | — | — |
