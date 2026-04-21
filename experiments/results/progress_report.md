# Auto-Caption Pipeline 진행 보고서

작성일: 2026-04-14
범위: HTML 개선 → 멀티-시그널 하이라이트 → 청크 사이즈 실험 종료 시점

---

## 0. 후속 업데이트 (2026-04-14, A1/A2/A3 closeout)

- **A1 완료**: Claude CLI usage 로깅 추가. 결과 문서: [2026-04-14_phase-a1_token-logging.md](2026-04-14_phase-a1_token-logging.md)
- **A2 완료**: token-based chunking(`chunk_max_tokens`, `chunk_tokenizer_encoding`) 도입. 결과 문서: [2026-04-15_phase-a2_token-chunking.md](2026-04-15_phase-a2_token-chunking.md)
- **A3 완료 (scoped)**: tiktoken under-count margin sampling. 결과 문서: [2026-04-15_phase-a3_token-margin-sampling.md](2026-04-15_phase-a3_token-margin-sampling.md). 30-min Korean talk 단일 샘플 × 5 chunks 측정 결과 `recommended_margin = 3.35×` (P95 3.1843 × 1.05, 올림). A2 의 1.80× 는 predicted≈10k 대역 특수해로 강등. `user_attributable − predicted` 가 chunk 크기와 무관하게 ~7.5k 로 상수인 additive overhead 가 본질이며, §6.3 에 multiplicative/additive 두 식이 모두 기록됨. **scope 한정: 길이/장르/밀도 축 일반화는 차단** (A3b/A4 로 이월).
- **현재 Phase A 잔여 범위**: A3b(1h/3h 길이 확대 실측), A4(장르/밀도 확대 + 풀 파이프라인 종단 테스트 + config 반영)
- **운영 결정 반영**:
  - `chunk_max_tokens` 는 opt-in 이며 precedence 는 `chunk_max_tokens > chunk_max_chars`
  - Claude usage sum 은 CLI cache_read 를 포함하므로 비용/예산 해석은 `input_tokens + cache_creation_input_tokens` 중심으로 봐야 함
  - 현재 `pipeline/config.py:25` `chunk_max_tokens=13200` 은 A2 1.80× 전제로 계산된 값. A3 의 3.35× (small-chunk 대역) 아래에서는 약 2배 under-budget. **config 수정은 A3b/A4 의 scope 확정 이후** (single-axis 일반화 차단)

---

## 1. 진행 상황 (What's done)

### 1.1 결과물 UX 개선 (HTML)
- **Tokyo Night 팔레트** 적용 (`#1a1b26` bg / `#c0caf5` 본문 / 액센트는 타임코드·통계 한정)
- **Centered Layout** — `max-width: 960px` + `.bleed-inner` 중앙 정렬, 720px 이하 반응형 분기
- **근거(evidence) 칸 기본 접힘** — 클릭으로 펼침, "모두 펼치기" 토글 버튼
- **mood별 좌측 컬러 보더** (hot / chat / chill / veryhot) — 분위기 즉시 식별
- **해시태그 칩 + pull quote 히어로** — 한눈에 방송 톤 파악

### 1.2 멀티-시그널 하이라이트 (3축 통합)
| 축 | 모듈 | 방식 |
|---|---|---|
| 채팅 반응 | `chat_analyzer.py` (기존) | Z-score 피크 + 키워드 가중치 |
| 자막 드라마성 | `subtitle_analyzer.py` (신규) | 강조어/웃음/단정문 사전 매칭 |
| 커뮤니티 매칭 | `community_matcher.py` (신규) | fmkorea 키워드 ↔ 자막 그렙 교차 |

→ `merge_results()` 프롬프트에 3축 시그널 모두 주입, "교차점 우선 선정" 명시

### 1.3 청크 사이즈 실험 + 기본값 변경
30분 클립(`12702452`)으로 4개 구성 비교:

| Config | Chunks | Timeline | /min | 총 소요 |
|---|---|---|---|---|
| baseline_150k | 1 | 10 | 0.33 | 174.6s |
| chunk_15k | 1 | 14 | 0.47 | 152.5s |
| chunk_8k | 2 | 13 | 0.43 | 219.0s |
| chunk_5k | **3** | **20** | **0.67** | 245.7s |

**결론**: 청크 수가 늘수록 타임라인 밀도 증가. `pipeline/config.py` 기본값 변경:
- `chunk_max_chars`: 150000 → **8000**
- `chunk_overlap_sec`: 45 → **30**

후속 완료 사항:
- A1 에서 `pipeline/claude_cli.py` 가 `Claude usage input_tokens=... output_tokens=... cache_creation_input_tokens=... cache_read_input_tokens=...` 를 INFO 로 남기도록 보강됨
- A2 에서 `pipeline/chunker.py` 에 token path 추가, `pipeline/main.py` fallback 을 `8000/30` 으로 정렬, same-source 비교표와 실측 결과를 [2026-04-15_phase-a2_token-chunking.md](2026-04-15_phase-a2_token-chunking.md)에 기록

### 1.4 프롬프트 강제 규칙 강화
- 해시태그 형식 명시 (`#단어` 백틱 금지)
- 근거 필드: 점수/퍼센트/카운트 금지, 실제 채팅 인용만
- 굵게 강조: 줄당 1회 (타임라인 엔트리 제목만)
- 에디터 노트: 산문, 불릿 금지
- 타임라인 밀도 스케일 명시 ("30분당 8~12, 3시간+ 20개")

---

## 2. 한계와 문제점

### 🔴 Critical (아키텍처 결함)

#### 2.1 Claude 토큰 예산을 전혀 고려하지 않음
- 이 항목은 **A1/A2에서 부분 해소**됐다.
- 현재는 char 경로와 별도로 **token 기준 분할**(`chunk_max_tokens`)이 존재한다.
- **사용량 모니터링**도 추가되어 각 성공 호출에서 `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens` 를 로깅한다.
- 남은 문제는 "토큰 가시성 부재"가 아니라 **장르/길이 확대 재측정 부족(A3)** 과 **종단 운영 검증 부족(A4)** 이다.

**필요**:
- 장르/길이별 `chunk_max_tokens` 운영 마진 재측정 (현재 A2 는 30분 한국어 샘플 1건)
- "1청크 = 컨텍스트 70% 사용" 같은 목표 수준을 A3 실측으로 보정
- cache_read/system prompt 오버헤드를 종단 비용 추정 규칙(A4/C1)으로 연결

#### 2.2 청크 사이즈 실험이 30분 1샘플만 검증
- 1시간/3시간 VOD에서 동일하게 작동하는지 모름
- 긴 VOD에서 청크 18개 → 20개 발생 시 `_two_round_merge` 진입, 토큰/시간 폭증 가능성
- 스트리머/장르별 발화 밀도 차이 미반영 (게임 vs 토크 vs 노래)

#### 2.3 실험이 구 프롬프트로 수행됨 (Python 모듈 캐싱)
- `_build_chunk_prompt` 개선 후 실험 재실행 안 함
- 결과적으로 "구 청크 프롬프트 + 신 병합 프롬프트" 혼합 상태 측정값
- 기본값 변경 결정의 근거가 부분적으로 오염됨

### 🟡 High (기능 결함)

#### 2.4 자막 강조어 사전이 빈약·고정
- 30개 단어 + 4개 패턴, 스트리머 관용구·신조어 누락 (`ㄹㅇ`, `킹받네`, `찐텐`, `외쳐 갓겜` 등)
- 문맥 없음: "진짜?" (의문) vs "진짜 미쳤다" (강조) 동일 점수
- 스트리머별 어휘 차이 무시 (탬탬버린 ↔ 다른 스트리머 일반화 안 됨)
- 단순 합산: 도배 시 점수 무한 증가

#### 2.5 SRT 전처리 파이프라인 미통합
- `srt-preprocessing.py` (고밀도 구간 추출) 자동 파이프라인에서 누락
- 현재 Whisper 원본 SRT → 그대로 청크 분할
- 잡담 구간이 청크 절반 차지하는 케이스 처리 못 함

#### 2.6 멀티-시그널이 "프롬프트 주입"에 그침
- 3축 시그널을 텍스트로 합쳐 Claude에게 전달만 할 뿐
- LLM이 정말 교차점을 우선시했는지 검증 메커니즘 없음
- 점수 가중 등 수치적 융합(score fusion) 안 함 → 결과 재현성 약함

#### 2.7 커뮤니티 매칭 정확도 미검증
- `_TOKEN_RE`가 한글 2자/영문 3자/숫자 2자 토큰 추출 — 너무 관대
- "ㅋㅋ" "그거" 같은 일반어가 stopwords 빠져 매칭될 가능성
- 실제 매칭 결과 샘플 검수 안 됨

### 🟢 Medium (운영 결함)

#### 2.8 종단 통합 테스트 부재
- 모니터링 → 다운로드 → 채팅 → 자막 → 요약 → HTML 까지 풀 파이프라인 1회 검증 없음
- 새 설정값(`chunk_max_chars=8000`)으로 실제 신규 VOD 처리 안 해봄

#### 2.9 비용 추적 없음
- Claude API 호출당 비용 로깅 없음
- 8000자 × N청크 + 병합 1회 = VOD당 얼마인지 불명
- 청크 수 늘수록 비용 선형 증가 — 운영 임계 기준 없음

#### 2.10 에러 복구가 단계별 저장에 의존
- VOD 처리 중간 실패 시 마지막 단계부터 재개 가능하지만, 어디까지 했는지 자동 판단 로직 약함
- 청크 6/12에서 실패 시 처음부터 다시 돌리는 케이스 발생 가능

---

## 3. 데이터로 보는 한계 요약

| 항목 | 측정값 | 이상값 | 갭 |
|---|---|---|---|
| 청크당 글자 수 | 8,000 | 토큰 기준 미정의 | **토큰화 안 됨** |
| 컨텍스트 활용률 | 미측정 | 70% 권장 | **모름** |
| 강조어 사전 크기 | 30개 | 200+ 권장 | **6배 부족** |
| 실험 표본 크기 | 30분 × 1 VOD | 다양한 길이/장르 | **샘플 1개** |
| 종단 테스트 횟수 | 0 | 최소 3 VOD | **미실행** |

---

## 4. 우선순위 다음 단계

### Phase A: 신뢰성 확보 (먼저 해야 함)
1. **완료 — 토큰 사용량 로깅** — `claude_cli.py`에 `usage` 파싱 추가, 결과: [2026-04-14_phase-a1_token-logging.md](2026-04-14_phase-a1_token-logging.md)
2. **완료 — 토큰 기준 분할로 전환** — `tiktoken` 도입, `chunk_max_tokens` 설정 추가, 결과: [2026-04-15_phase-a2_token-chunking.md](2026-04-15_phase-a2_token-chunking.md)
3. **진행 필요 — 실험 재실행** — 새 청크 프롬프트 + 토큰 측정 포함, 30분/1시간/3시간 3샘플
4. **진행 필요 — 풀 파이프라인 종단 테스트** — 신규 VOD 1개 자동 처리 → HTML까지 검수

### Phase B: 품질 향상
5. **강조어 사전 확장** — 스트리머 관용구·신조어 100개 추가, 또는 TF-IDF 동적 키워드
6. **커뮤니티 매칭 검수** — 실제 매칭 샘플 30개 수동 확인, stopwords 보강
7. **SRT 전처리 통합 결정** — 필요/불필요 판단 후 통합 또는 명시적 제거

### Phase C: 운영 성숙도
8. **비용 모니터링** — VOD당 토큰·비용 집계, 일일 리포트
9. **재개 로직 강화** — 단계별 체크포인트 자동 감지
10. **장르별 프로파일** — 스트리머/카테고리별 청크/강조어 설정 분기

---

### Phase C: 품질 — 고유명사 보정 (2026-04-21 추가)
11. **완료 — 스트리머별 lexicon + 사후 교정** — `pipeline/lexicon.py` + `scripts/recorrect_reports.py`. Whisper initial_prompt + Claude 청크/통합 단계 + 사후 매핑 4중 방어. 16 VOD 중 7건 실제 교정·배포 완료. 회귀 테스트: `experiments/test_recorrect_apply.py`. 결과: [2026-04-21_phase-c_lexicon-recorrect.md](2026-04-21_phase-c_lexicon-recorrect.md)

---

## 5. 한 줄 요약

**토큰 가시성(A1)과 token chunking(A2)은 확보됐지만, 운영 가능한 기본값을 확정하려면 A3/A4 실측이 더 필요하다. 별도로 고유명사 오인식은 Phase C 에서 4중 방어선으로 닫혔다.**
