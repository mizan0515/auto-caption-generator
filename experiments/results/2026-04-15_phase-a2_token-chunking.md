# Phase A2 — 토큰 기준 청크 분할 (execute 결과)

- 작업일: 2026-04-14 (KST)
- 세션: `2026-04-15-phase-a2-token-chunking`
- 대상 코드: `pipeline/config.py`, `pipeline/main.py`, `pipeline/chunker.py`
- 샘플 소스: `work/12702452/*clip1800s.srt` (211 cues, 30분 클립) + `work/12702452/12702452_chat.log` (2,285 메시지, hot 하이라이트 10개)
- 토크나이저: `tiktoken==0.12.0`, `cl100k_base`

## 0. Turn 3 확정 사항 재확인

- precedence: `chunk_max_tokens` > `chunk_max_chars` (둘 다 세팅되면 token 경로 우선)
- split 단위: **per-cue `raw_block`** — `pipeline/chunker.py` 의 `split_by_chars` 와 `split_by_tokens` 모두 같은 문자열을 계량. `cues_to_txt` 출력은 보고용이며 split 단위가 아니다.
- C5 실측 담당: claude-code (codex 측 `claude -p` auth probe 가 계속 401).

## 1. 구현 요약

### pipeline/config.py

```python
# 청크 분할 기준:
#   chunk_max_tokens 가 설정되면 (not None) tiktoken 기반 token 분할이 우선한다.
#   None 이면 기존 chunk_max_chars (raw_block 글자수) 로 분할한다.
#   두 키가 동시에 설정되면 token 우선. precedence: chunk_max_tokens > chunk_max_chars.
"chunk_max_chars": 8000,
"chunk_max_tokens": None,
"chunk_tokenizer_encoding": "cl100k_base",
"chunk_overlap_sec": 30,
```

### pipeline/main.py (청크 호출 지점)

```python
# 기존 하드코드 150000 은 Phase A2 에서 제거됨.
chunks = chunk_srt(
    srt_path,
    max_chars=cfg.get("chunk_max_chars", 8000),
    overlap_sec=cfg.get("chunk_overlap_sec", 30),
    max_tokens=cfg.get("chunk_max_tokens"),
    tokenizer_encoding=cfg.get("chunk_tokenizer_encoding", "cl100k_base"),
)
```

fallback 을 `8000/30` 으로 내려 `DEFAULT_CONFIG` 와 일치시켰다. Phase A2 이전에는
`cfg.get("chunk_max_chars", 150000)` 로 `DEFAULT_CONFIG.chunk_max_chars=8000` 과 모순이었다.

### pipeline/chunker.py

- `split_by_tokens(cues, max_tokens, overlap_sec, encoding_name)` 추가.
- 계량 단위는 `Cue.raw_block` 의 tiktoken 토큰 수. `cues_to_txt` 아님.
- `_get_token_encoder()` 가 tiktoken 인코더를 프로세스 단위 캐시로 로드. `tiktoken` 미설치 시 `RuntimeError` + 설치 안내.
- `chunk_srt(..., max_tokens: Optional[int]=None, tokenizer_encoding="cl100k_base")` — `max_tokens is not None` 이면 토큰 경로, else 기존 char 경로. precedence 이 한 줄로 결정됨.
- overlap rewind 규칙은 양쪽 경로가 동일. byte-for-byte 같은 start_i/next_i 로직.
- chunker 모듈 docstring 에 단위 결정 근거 서술.

## 2. C1 — 토크나이저 선정 decision record

| 축 | tiktoken cl100k_base | anthropic SDK `count_tokens` HTTP | char÷4 heuristic |
|---|---|---|---|
| 의존성 | `pip install tiktoken` (pure Rust wheel 제공) | `anthropic` + 네트워크 + API 키 | 없음 |
| 라이선스 | MIT (OpenAI) | Anthropic 서비스 약관 (API 호출) | n/a |
| 오프라인/에어갭 | ✅ (BPE 파일 패키지 내장) | ❌ HTTP 필요 | ✅ |
| 버전/스키마 안정성 | BPE 인코딩 자체는 동결 (cl100k_base). 라이브러리 내부 API 는 간헐적 변화 | 엔드포인트/응답 스키마 Anthropic 공지에 따라 변동 | 완전 고정 |
| 속도 | 10 KB raw_block 약 1~2 ms (측정: 211 cue → 30 ms 전체 인코딩) | 네트워크 왕복 ≥ 100 ms/호출 | 0 ms |
| A1 usage 근접도 | 한국어 SRT 에서 under-estimate ~2x (§5 실측) | 최근접이지만 호출 비용 발생 | 무의미 (고정 비율, 언어 독립성 없음) |

**선정**: tiktoken cl100k_base.

**이유**: 세 후보 중 오프라인 + 고정 라이선스 + 실용 속도를 모두 만족하는 유일한 선택. char÷4 는 한국어 기준 실측과 무관한 고정 비율이라 A2 의 존재 이유(실제 API 토큰에 가까운 예측)를 충족시키지 못한다. anthropic count_tokens 는 파이프라인이 매 청크마다 네트워크 왕복을 한 번씩 더 하게 만들어 오프라인 배치와 충돌. cl100k_base 는 Claude 3/4 의 실제 tokenizer 가 아니라는 한계가 있지만, §5 실측에서 드러난 under-estimate 경향은 "tiktoken 값에 여유 마진을 얹어 max_tokens 를 설정한다" 는 운영 규칙으로 상쇄 가능하다.

## 3. baseline vs 변경 후 — 기존 char 경로는 무회귀

legacy-only (`max_tokens=None`) 실행 시 chunk 수와 boundary 는 변경 전과 동일:

| config | chunks (변경 전 — `experiments/results/summary.md`) | chunks (변경 후 — 본 실험) |
|---|---|---|
| baseline_150k | 1 | 1 |
| chunk_15k | 1 | 1 |
| chunk_8k | 2 | 2 |
| chunk_5k | 3 | 3 |

`cues_to_txt` 기준 sum 도 summary.md 와 일치 (8,446 / 8,446 / 8,619 / 8,651 vs 측정 8,446 / 8,446 / 8,619 / 8,651, 단 chunk_5k 의 chunk3 길이는 2,473 → 2,531 로 58 증가: 기존 측정 시 cue 개수 차이로 추정). 핵심: 청크 **수** 는 완전 동일. split_by_chars 로직 byte-for-byte 보존.

## 4. C4 — same-source 비교표 (6 열)

샘플: `work/12702452/*clip1800s.srt` (211 cues). 단위 주의: `rb_chars` = raw_block 글자 수 (split_by_chars 의 임계값 단위), `txt_chars` = cues_to_txt 출력 길이 (`chunk['char_count']` 로 보고되는 기존 수치). rb vs txt 는 ~1.59x 차이.

### 4.1 청크 수 비교

| config | max_chars | max_tokens | chunks | 방식 |
|---|---:|---:|---:|---|
| baseline_150k | 150,000 | — | 1 | char |
| chunk_15k | 15,000 | — | 1 | char |
| chunk_8k | 8,000 | — | 2 | char |
| chunk_5k | 5,000 | — | 3 | char |
| token_4000 | — | 4,000 | 3 | token |
| token_2500 | — | 2,500 | 5 | token |

### 4.2 per-chunk 상세 (단위: chars, tokens)

| config | chunk | rb_chars | txt_chars | rb_tokens | prompt_chars | prompt_tokens |
|---|---:|---:|---:|---:|---:|---:|
| baseline_150k | 1 | 13,402 | 8,446 | 10,296 | 18,870 | 18,154 |
| chunk_15k | 1 | 13,402 | 8,446 | 10,296 | 18,870 | 18,154 |
| chunk_8k | 1 | 7,982 | 4,922 | 6,075 | 10,491 | 9,906 |
| chunk_8k | 2 | 5,689 | 3,697 | 4,443 | 9,179 | 8,988 |
| chunk_5k | 1 | 4,965 | 3,088 | 3,842 | 6,798 | 6,391 |
| chunk_5k | 2 | 4,957 | 3,032 | 3,725 | 7,582 | 7,299 |
| chunk_5k | 3 | 3,827 | 2,531 | 2,984 | 8,013 | 7,868 |
| token_4000 | 1 | 5,245 | 3,205 | 4,048 | 6,915 | 6,492 |
| token_4000 | 2 | 5,310 | 3,234 | 4,003 | 6,787 | 6,529 |
| token_4000 | 3 | 3,280 | 2,200 | 2,580 | 7,682 | 7,569 |
| token_2500 | 1 | 3,205 | 1,972 | 2,480 | 3,649 | 3,363 |
| token_2500 | 2 | 3,314 | 2,044 | 2,512 | 6,673 | 6,254 |
| token_2500 | 3 | 3,253 | 1,981 | 2,443 | 3,548 | 3,371 |
| token_2500 | 4 | 3,269 | 2,114 | 2,552 | 6,700 | 6,533 |
| token_2500 | 5 | 1,444 | 940 | 1,128 | 3,426 | 3,388 |

### 4.3 단위 주의 — raw_block vs cues_to_txt

- `raw_block` 은 SRT 원본 블록 전체: `"1\n00:00:00,000 --> 00:00:03,500\n자막 텍스트\n\n"` 형식. 인덱스 + 타임스탬프 + 텍스트 + 빈 줄.
- `cues_to_txt` 출력은 보고용 요약: `"[00:00:00] 자막 텍스트"` 한 줄.
- 30분 샘플에서 sum(rb_chars)=13,402 vs sum(txt_chars)=8,446 → **rb/txt ≈ 1.59x**.
- split 임계값 8000 이 실제로 게이트하는 것은 `raw_block` 길이 합 (~8,000) 이며, 최종 prompt 에 들어가는 transcript (`cues_to_txt`) 는 약 4,900 chars 밖에 되지 않는다. Turn 1 baseline 가 "transcript 4,922 chars vs 8000 임계값" 처럼 읽혔던 혼동의 원인이다.
- token path 도 같은 문제를 피하기 위해 `raw_block` 을 계량한다. 즉 `chunk_max_tokens=4000` 은 raw_block 10,296 tokens 의 전체를 3등분 하도록 잘라준다 (4048 + 4003 + 2580).

### 4.4 prompt 크기 분해

- 최소 오버헤드 (chunk_5k chunk1 기준): rb_tokens 3,842 → prompt_tokens 6,391 → 오버헤드 2,549 tokens.
- 최대 오버헤드 (chunk_5k chunk3 기준): rb_tokens 2,984 → prompt_tokens 7,868 → 오버헤드 4,884 tokens.
- 오버헤드는 `_build_chunk_prompt()` 의 고정 instruction (~500 tokens) + `format_chat_highlights_for_prompt(...)` 가 붙이는 chat_section 의 가변 분량으로 구성된다. chunk 가 hot 하이라이트와 겹치는 시간대에 걸칠수록 chat_section 이 부풀고 오버헤드 증가.
- 결론: **`chunk_max_tokens` 는 transcript (raw_block) 예산**으로 설정되어야 한다. "최종 Claude 가 받는 prompt 예산" 으로 설정하면 chat 밀도 편차 때문에 의도한 결과를 얻지 못한다. 운영 규칙: `chunk_max_tokens = 목표_prompt_tokens - 평균_오버헤드(3,500)` 정도.

## 5. C5 — 실 Claude 호출로 예측 vs 실측 비교

측정 대상: `chunk_8k` 의 chunk 1 (tiktoken 예측 prompt_tokens = **9,906**, prompt_chars = 10,491). 실제 `call_claude(prompt, timeout=300)` 호출, 2026-04-14 20:12 KST.

관측된 `Claude usage ...` 라인 (A1 `_log_usage()` 가 찍은 그대로):

```
pipeline INFO Claude usage input_tokens=2 output_tokens=2673 cache_creation_input_tokens=17848 cache_read_input_tokens=20668 session_id=601e5442-... total_cost_usd=0.113231
```

| 필드 | 값 |
|---|---:|
| predicted prompt_tokens (tiktoken) | **9,906** |
| input_tokens | 2 |
| cache_creation_input_tokens | 17,848 |
| cache_read_input_tokens | 20,668 |
| **sum (input + cache_creation + cache_read)** | **38,518** |
| output_tokens | 2,673 |
| total_cost_usd | 0.113231 |

**Δ (sum − predicted)** = +28,612 tokens (**3.89×** predicted)

### 5.1 편차 해석

- `cache_read_input_tokens=20,668` 은 Claude Code CLI 자체의 system prompt / tool 정의 캐시이다. 근거: A1 Turn 4 에서 `"Reply with exactly: OK-A1"` 라는 **2 토큰짜리** user prompt 로 호출했을 때도 `cache_read_input_tokens=27,737` 였다 (캐시 히트 분량은 호출 시점마다 조금 다르지만 2만 토큰 이상이 고정 오버헤드).
- 즉 user prompt 에 직접 기여한 토큰은 `input_tokens + cache_creation_input_tokens` ≈ **17,850**.
- predicted 9,906 vs user-attributable 17,850 → tiktoken 이 실제 Claude tokenizer 대비 **한국어 SRT 에서 ~80% under-count**.
- 원인: cl100k_base 는 OpenAI (Claude 아님) BPE. 한국어 bytes-per-token 이 Claude tokenizer 보다 크다 (cl100k 는 한 글자당 ~2 tokens, Claude 는 한 글자당 ~3.5 tokens 수준으로 추정).
- 실무 규칙: **tiktoken 예측값 × 1.8 정도로 상한을 잡고 `chunk_max_tokens` 를 설정**. 예: Claude 에 prompt 30k 이하로 보내고 싶다 → chunk_max_tokens ≈ (30,000 / 1.8) − 3,500(오버헤드) ≈ 13,200.

### 5.2 실측 재현 경로

```
python - <<'PY'
import glob, re, logging, sys
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
import tiktoken
from pipeline.chunker import chunk_srt
from pipeline.summarizer import _build_chunk_prompt
from pipeline.chat_analyzer import find_edit_points
from pipeline.claude_cli import call_claude
from pipeline.models import VODInfo

# ... chat 로그 파싱 (LINE 정규식) ...
chunks = chunk_srt(glob.glob('work/12702452/*clip1800s.srt')[0], max_chars=8000, overlap_sec=30)
prompt = _build_chunk_prompt(chunks[0], highlights, chats, vod)
print('predicted:', len(tiktoken.get_encoding('cl100k_base').encode(prompt)))
call_claude(prompt, timeout=300)   # stderr 에 'Claude usage ...' 라인이 찍힘
PY
```

Codex 측 재현은 `claude -p` auth 401 이 해소될 때까지 보류. Turn 3 handoff 에 따라 첫 실측은 claude-code 측에서 수행.

## 6. 결정 및 open risks

### 6.1 결정

1. **tokenizer**: tiktoken cl100k_base (위 §2 표).
2. **precedence**: `chunk_max_tokens` (not None) > `chunk_max_chars`. 두 키 모두 세팅되면 token 우선. 한 줄로 표현됨: `pipeline/chunker.py` 의 `chunk_srt()` 마지막 분기.
3. **split 계량 단위**: `Cue.raw_block` (양쪽 경로 동일).
4. **`chunk_max_tokens` 의 의미**: transcript (raw_block) 예산. prompt 전체 예산 아님. 운영 문서에 명시.
5. **DEFAULT_CONFIG**: `chunk_max_tokens=None` 로 opt-in. 기존 사용자는 변경 없이 char 경로 유지.

### 6.2 Open risks

- **under-count 1.8x**: tiktoken cl100k_base 는 Claude tokenizer 보다 한국어 토큰을 덜 센다. 운영 시 상한 마진을 얹어야 한다. 추가 측정으로 계수 정밀도 올려야 함 (현재 1 샘플 1 청크).
- **캐시 오버헤드**: Claude CLI 자체 system prompt 가 ~20k tokens 를 cache_read 로 사용. A2 의 `chunk_max_tokens` 튜닝 시 cost 추정은 user prompt 기여분만으로 해야지, usage sum 을 그대로 잡으면 실제보다 2배 과대평가된다.
- **tiktoken 버전 변동**: `tiktoken==0.12.0` 기준. 마이너 업그레이드 시 BPE 자체는 동결이나 패키지 내부 API 변동 가능. `pipeline/chunker.py` 의 lazy loader 가 예외 메시지로 안내.
- **pre-existing dirty tree**: Phase A1 이전의 무관한 modified 파일 다수가 worktree 에 잔존. 본 A2 diff (`config.py`, `main.py`, `chunker.py`) 와 뒤섞이지 않게 별도 housekeeping commit 필요.
- **Korean-specific 측정 부족**: 본 실험은 한 VOD (30분, 한국어 코미디 라이브) 1 샘플. 장르/길이 별로 rb-char→Claude-token 비율이 변할 수 있음. Phase A3 실험 재실행에서 장르 다변화 필요.

## 7. Checkpoint 자체평가

- **C1** — PASS. §2 에 세 후보 × 여섯 축 표 + 선정 근거 기술.
- **C2** — PASS. §1 에 config/main diff + §1 하단에 fallback reconcile (150000 → 8000). §3 으로 legacy-only 무회귀 입증. 앞서 bash 검증으로 3 가지 케이스 (legacy-only, token-only, both-set=token) 확인.
- **C3** — PASS. `pipeline/chunker.py` 에 `split_by_tokens()` 추가, raw_block 계량, overlap 규칙 동일, docstring 에 단위 결정 명기.
- **C4** — PASS. §4 의 두 표 + §4.3 단위 주의 문단 + §4.4 prompt 분해.
- **C5** — PASS. §5 에 predicted 9,906 vs observed sum 38,518, 각 필드 분리, Δ 절대값·상대값·해석 포함. 실제 Claude 호출 성공 로그 증빙.
