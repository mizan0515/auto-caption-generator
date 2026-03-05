"""SRT 전처리 — 고밀도 구간 추출 페이지"""

import re
import os
from datetime import timedelta
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="SRT 전처리",
    page_icon="📝",
    layout="centered",
)

# ──────────────────────────────────────────────
# 핵심 로직 (srt-preprocessing.py 와 동일)
# ──────────────────────────────────────────────

def parse_ts(ts: str) -> float:
    """'HH:MM:SS,mmm' → 초(float)"""
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def format_ts(sec: float) -> str:
    td = timedelta(seconds=max(0, sec))
    total = int(td.total_seconds())
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def load_srt(path: Path):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", raw.strip())
    items = []
    for b in blocks:
        lines = b.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.search(r"(\d\d:\d\d:\d\d,\d+)\s*-->\s*(\d\d:\d\d:\d\d,\d+)", lines[1])
        if not m:
            continue
        start = parse_ts(m.group(1))
        end = parse_ts(m.group(2))
        text = " ".join(lines[2:]).strip()
        if text:
            items.append((start, end, text))
    return items


def build_candidates(
    items,
    window_sec: int = 20,
    top_ratio: float = 0.10,
    pad_sec: int = 40,
    sample_lines: int = 10,
):
    start0 = min(s for s, _, _ in items)
    end0 = max(e for _, e, _ in items)

    n_bins = int((end0 - start0) // window_sec) + 1
    bins = [{"lines": 0, "chars": 0} for _ in range(n_bins)]

    for s, _, t in items:
        idx = int((s - start0) // window_sec)
        if 0 <= idx < n_bins:
            bins[idx]["lines"] += 1
            bins[idx]["chars"] += len(t)

    scores = [b["lines"] for b in bins]
    avg_lines = (sum(scores) / len(scores)) if scores else 0

    sorted_scores = sorted(scores)
    cut_idx = int((1 - top_ratio) * len(sorted_scores))
    cut_idx = max(0, min(cut_idx, len(sorted_scores) - 1))
    threshold = sorted_scores[cut_idx]

    hot = [i for i, sc in enumerate(scores) if sc >= threshold and sc > 0]

    merged = []
    for i in hot:
        if not merged or i > merged[-1][1] + 1:
            merged.append([i, i])
        else:
            merged[-1][1] = i

    candidates = []
    for a, b in merged:
        seg_start = start0 + a * window_sec
        seg_end = start0 + (b + 1) * window_sec

        seg_start2 = max(start0, seg_start - pad_sec)
        seg_end2 = min(end0, seg_end + pad_sec)

        lines_sum = sum(bins[i]["lines"] for i in range(a, b + 1))
        chars_sum = sum(bins[i]["chars"] for i in range(a, b + 1))

        local_avg = lines_sum / (b - a + 1)
        density = (local_avg / avg_lines) if avg_lines > 0 else 0.0

        candidates.append(
            {
                "start": seg_start2,
                "end": seg_end2,
                "lines": lines_sum,
                "chars": chars_sum,
                "density": density,
            }
        )

    # 패딩 적용 후 겹치는 후보 구간 병합
    candidates.sort(key=lambda c: c["start"])
    merged_candidates = []
    for c in candidates:
        if merged_candidates and c["start"] <= merged_candidates[-1]["end"]:
            prev = merged_candidates[-1]
            prev["end"] = max(prev["end"], c["end"])
            prev["lines"] += c["lines"]
            prev["chars"] += c["chars"]
            prev["density"] = max(prev["density"], c["density"])
        else:
            merged_candidates.append(c)

    # 병합된 구간 기준으로 sample 수집
    for c in merged_candidates:
        sample = [(s, t) for s, _, t in items if c["start"] <= s <= c["end"]]
        sample.sort(key=lambda x: x[0])
        c["sample"] = sample[:sample_lines]

    return merged_candidates


def render_output(candidates: list) -> str:
    """후보 목록 → 출력 문자열"""
    lines = ["[CANDIDATE_CLIPS]"]
    for c in candidates:
        lines.append(
            f"[{format_ts(c['start'])}~{format_ts(c['end'])}] "
            f"lines={c['lines']} chars={c['chars']} density={c['density']:.2f}x"
        )
        for ts, t in c["sample"]:
            t2 = t.replace("\n", " ")
            if len(t2) > 80:
                t2 = t2[:80] + "…"
            lines.append(f"- [{format_ts(ts)}] {t2}")
        lines.append("")
    lines.append(f"# 후보 개수: {len(candidates)}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 세션 상태 초기화
# ──────────────────────────────────────────────

_DEFAULTS = {
    "srt_path": "",
    "srt_result": None,   # 마지막 처리 결과 문자열
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ──────────────────────────────────────────────
# 파일 다이얼로그 헬퍼
# ──────────────────────────────────────────────

def pick_srt_file():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    result = filedialog.askopenfilename(
        filetypes=[("SRT 파일", "*.srt"), ("텍스트 파일", "*.txt"), ("모든 파일", "*.*")]
    )
    root.destroy()
    return result or ""


# ──────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────

st.title("📝 SRT 전처리 — 고밀도 구간 추출")
st.caption("자막 밀도가 높은 구간(핵심 장면)을 자동으로 찾아 후보 클립 목록을 출력합니다.")

st.divider()

# ── 파일 선택 ──
with st.container(border=True):
    st.subheader("SRT 파일")
    col_input, col_btn = st.columns([5, 1])
    with col_input:
        entered = st.text_input(
            "SRT 파일 경로",
            value=st.session_state.srt_path,
            placeholder=r"C:\path\to\subtitles.srt",
            label_visibility="collapsed",
        )
        st.session_state.srt_path = entered.strip()
    with col_btn:
        if st.button("📂", use_container_width=True, help="파일 선택"):
            picked = pick_srt_file()
            if picked:
                st.session_state.srt_path = picked
                st.session_state.srt_result = None  # 새 파일이면 결과 초기화
                st.rerun()

    if st.session_state.srt_path:
        p = st.session_state.srt_path
        exists = os.path.isfile(p)
        if exists:
            size_kb = os.path.getsize(p) / 1024
            st.caption(f"✅ `{os.path.basename(p)}` ({size_kb:.1f} KB)")
        else:
            st.caption(f"⚠️ 파일을 찾을 수 없습니다: `{p}`")
    else:
        st.caption("SRT 파일 경로를 직접 입력하거나 📂 버튼으로 선택하세요.")

st.write("")

# ── 옵션 ──
with st.container(border=True):
    st.subheader("옵션")

    col1, col2 = st.columns(2)

    with col1:
        window_sec = st.number_input(
            "윈도우 (초)",
            min_value=5,
            max_value=300,
            value=20,
            step=5,
            help="밀도를 계산할 시간 단위 구간 (기본: 20초)",
        )
        pad_sec = st.number_input(
            "패딩 (초)",
            min_value=0,
            max_value=300,
            value=40,
            step=10,
            help="후보 구간 앞뒤에 추가할 여유 시간 (기본: 40초)",
        )

    with col2:
        top_pct = st.slider(
            "상위 비율 (%)",
            min_value=1,
            max_value=50,
            value=50,
            step=1,
            help="전체 구간 중 밀도 상위 몇 %를 후보로 선택할지 (기본: 50%)",
        )
        top_ratio = top_pct / 100.0

        sample_lines = st.number_input(
            "샘플 줄 수",
            min_value=1,
            max_value=500,
            value=50,
            step=1,
            help="각 후보 구간에서 보여줄 최대 자막 줄 수 (기본: 50줄)",
        )

st.write("")

# ── 출력 방식 ──
output_mode = st.radio(
    "출력 방식",
    ["화면에 표시", "TXT 파일 다운로드"],
    horizontal=True,
)

st.write("")

# ── 실행 버튼 ──
run_btn = st.button(
    "▶  분석 실행",
    type="primary",
    use_container_width=True,
)

if run_btn:
    srt_path = st.session_state.srt_path
    if not srt_path:
        st.error("SRT 파일 경로를 입력하세요.")
    elif not os.path.isfile(srt_path):
        st.error(f"파일을 찾을 수 없습니다: `{srt_path}`")
    else:
        with st.spinner("SRT 파싱 중..."):
            items = load_srt(Path(srt_path))

        if not items:
            st.error("SRT 파싱 실패: 인코딩/형식을 확인하세요 ('HH:MM:SS,ms --> ...' 형태여야 합니다).")
        else:
            with st.spinner(f"{len(items)}개 자막 항목 분석 중..."):
                candidates = build_candidates(
                    items,
                    window_sec=int(window_sec),
                    top_ratio=top_ratio,
                    pad_sec=int(pad_sec),
                    sample_lines=int(sample_lines),
                )
            st.session_state.srt_result = render_output(candidates)
            st.session_state.srt_result_meta = {
                "filename": os.path.splitext(os.path.basename(srt_path))[0],
                "n_items": len(items),
                "n_candidates": len(candidates),
            }

# ── 결과 표시 ──
if st.session_state.srt_result:
    result_text = st.session_state.srt_result
    meta = st.session_state.get("srt_result_meta", {})

    st.divider()
    st.subheader("결과")

    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.metric("자막 항목 수", meta.get("n_items", "-"))
    with col_info2:
        st.metric("후보 구간 수", meta.get("n_candidates", "-"))

    if output_mode == "화면에 표시":
        st.code(result_text, language=None)

    else:  # TXT 파일 다운로드
        filename = meta.get("filename", "srt_candidates")
        st.download_button(
            label="⬇️  TXT 파일 다운로드",
            data=result_text.encode("utf-8"),
            file_name=f"{filename}_candidates.txt",
            mime="text/plain",
            use_container_width=True,
            type="primary",
        )
        # 미리보기
        with st.expander("결과 미리보기", expanded=False):
            st.code(result_text, language=None)
