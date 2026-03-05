"""SRT 청크 분할 — LLM 투입용 txt 청크 생성 페이지"""

import io
import json
import os
import re
import zipfile
from dataclasses import dataclass
from typing import List

import streamlit as st

from utils import pick_file, pick_directory, read_srt_text

st.set_page_config(
    page_title="SRT 청크 분할",
    page_icon="✂️",
    layout="centered",
)

# ──────────────────────────────────────────────
# 핵심 로직 (srt-chunk.py 와 동일)
# ──────────────────────────────────────────────

SRT_TS_RE = re.compile(r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})")
TIME_LINE_RE = re.compile(r"^\s*(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    start_ts: str
    end_ts: str
    text_lines: List[str]
    raw_block: str


def ts_to_ms(ts: str) -> int:
    m = SRT_TS_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Invalid timestamp: {ts}")
    return (((int(m.group("h")) * 60 + int(m.group("m"))) * 60) + int(m.group("s"))) * 1000 + int(m.group("ms"))


def ms_to_hhmmss(ms: int) -> str:
    sec = ms // 1000
    h = sec // 3600
    sec %= 3600
    return f"{h:02d}:{sec // 60:02d}:{sec % 60:02d}"


def parse_srt(content: str) -> List[Cue]:
    blocks = re.split(r"\n{2,}", content.strip(), flags=re.MULTILINE)
    cues: List[Cue] = []
    for b in blocks:
        lines = [ln.rstrip("\n") for ln in b.splitlines()]
        if len(lines) < 2:
            continue
        time_i = next((i for i, ln in enumerate(lines[:6]) if TIME_LINE_RE.match(ln)), None)
        if time_i is None:
            continue
        m = TIME_LINE_RE.match(lines[time_i])
        start_ts, end_ts = m.group(1), m.group(2)
        cues.append(Cue(
            start_ms=ts_to_ms(start_ts),
            end_ms=ts_to_ms(end_ts),
            start_ts=start_ts,
            end_ts=end_ts,
            text_lines=lines[time_i + 1:],
            raw_block="\n".join(lines) + "\n\n",
        ))
    cues.sort(key=lambda c: (c.start_ms, c.end_ms))
    return cues


def cues_to_txt(cues: List[Cue]) -> str:
    out = []
    for c in cues:
        text = " ".join(ln.strip() for ln in c.text_lines if ln.strip())
        if text:
            out.append(f"[{ms_to_hhmmss(c.start_ms)}] {text}")
    return "\n".join(out).rstrip() + "\n"


def split_by_duration(cues: List[Cue], max_duration_sec: int, overlap_sec: int) -> List[List[Cue]]:
    max_ms = max_duration_sec * 1000
    overlap_ms = overlap_sec * 1000
    chunks, i, n = [], 0, len(cues)
    while i < n:
        start_i = i
        chunk_end_target = cues[i].start_ms + max_ms
        j = i
        while j < n and cues[j].start_ms <= chunk_end_target:
            j += 1
        if j < n and overlap_ms > 0:
            rewind_ms = max(0, cues[j].start_ms - overlap_ms)
            k = j
            while k > start_i and cues[k - 1].start_ms >= rewind_ms:
                k -= 1
            next_i = k
        else:
            next_i = j
        chunks.append(cues[i:j])
        i = max(next_i, i + 1)
    return chunks


def split_by_chars(cues: List[Cue], max_chars: int, overlap_sec: int) -> List[List[Cue]]:
    overlap_ms = overlap_sec * 1000
    chunks, i, n = [], 0, len(cues)
    while i < n:
        start_i = i
        char_count, j = 0, i
        while j < n:
            blk_len = len(cues[j].raw_block)
            if j > i and char_count + blk_len > max_chars:
                break
            char_count += blk_len
            j += 1
        if j < n and overlap_ms > 0:
            rewind_ms = max(0, cues[j].start_ms - overlap_ms)
            k = j
            while k > start_i and cues[k - 1].start_ms >= rewind_ms:
                k -= 1
            next_i = k
        else:
            next_i = j
        chunks.append(cues[i:j])
        i = max(next_i, i + 1)
    return chunks


def build_results(chunks: List[List[Cue]], base_name: str):
    """청크 목록 → (manifest list, {filename: txt_content} dict)"""
    manifest = []
    files = {}
    for idx, ch in enumerate(chunks, 1):
        if not ch:
            continue
        start_ms = ch[0].start_ms
        end_ms = max(c.end_ms for c in ch)
        start_h = ms_to_hhmmss(start_ms)
        end_h = ms_to_hhmmss(end_ms)
        fn = f"{base_name}.chunk_{idx:03d}.{start_h.replace(':','')}-{end_h.replace(':','')}.txt"
        txt = cues_to_txt(ch)
        files[fn] = txt
        manifest.append({
            "chunk_index": idx,
            "file_txt": fn,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start_hhmmss": start_h,
            "end_hhmmss": end_h,
            "cue_count": len(ch),
            "char_count": len(txt),
        })
    return manifest, files


def make_zip(files: dict, manifest: list, base_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn, txt in files.items():
            zf.writestr(fn, txt.encode("utf-8"))
        zf.writestr(
            f"{base_name}.manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    return buf.getvalue()


# ──────────────────────────────────────────────
# 세션 상태 초기화
# ──────────────────────────────────────────────

for k, v in {"chunk_srt_path": "", "chunk_result": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v


SRT_FILETYPES = [("SRT 파일", "*.srt"), ("모든 파일", "*.*")]


# ──────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────

st.title("✂️ SRT 청크 분할")
st.caption("대용량 SRT를 LLM 투입용 txt 청크로 분할합니다. 각 청크는 `[HH:MM:SS] 자막` 형식의 타임스탬프 텍스트로 저장됩니다.")

st.divider()

# ── 파일 선택 ──
with st.container(border=True):
    st.subheader("SRT 파일")
    col_input, col_btn = st.columns([5, 1])
    with col_input:
        entered = st.text_input(
            "SRT 경로",
            value=st.session_state.chunk_srt_path,
            placeholder=r"C:\path\to\subtitles.srt",
            label_visibility="collapsed",
        )
        st.session_state.chunk_srt_path = entered.strip()
    with col_btn:
        if st.button("📂", use_container_width=True, help="파일 선택"):
            picked = pick_file(filetypes=SRT_FILETYPES)
            if picked:
                st.session_state.chunk_srt_path = picked
                st.session_state.chunk_result = None
                st.rerun()

    if st.session_state.chunk_srt_path:
        p = st.session_state.chunk_srt_path
        if os.path.isfile(p):
            size_kb = os.path.getsize(p) / 1024
            st.caption(f"✅ `{os.path.basename(p)}` ({size_kb:.1f} KB)")
        else:
            st.caption(f"⚠️ 파일을 찾을 수 없습니다: `{p}`")
    else:
        st.caption("SRT 파일 경로를 직접 입력하거나 📂 버튼으로 선택하세요.")

st.write("")

# ── 분할 옵션 ──
with st.container(border=True):
    st.subheader("분할 옵션")

    split_mode = st.radio(
        "분할 기준",
        ["시간 기준", "글자 수 기준"],
        horizontal=True,
        help="시간 기준: 청크당 최대 재생 시간 / 글자 수 기준: 청크당 최대 문자 수",
    )

    col1, col2 = st.columns(2)
    with col1:
        if split_mode == "시간 기준":
            max_duration = st.number_input(
                "청크당 최대 시간 (초)",
                min_value=60,
                max_value=7200,
                value=900,
                step=60,
                help="기본 900초 (15분). 이 시간을 초과하면 새 청크로 분할.",
            )
            max_chars = 0
        else:
            max_chars = st.number_input(
                "청크당 최대 글자 수",
                min_value=10000,
                max_value=500000,
                value=180000,
                step=10000,
                help="기본 180,000자. Claude 기준 약 45K 토큰에 해당.",
            )
            max_duration = 0

    with col2:
        overlap_sec = st.number_input(
            "오버랩 (초)",
            min_value=0,
            max_value=300,
            value=30,
            step=10,
            help="청크 경계에서 앞 청크 끝부분을 다음 청크에 중복 포함하는 시간. 문맥 유지용.",
        )

st.write("")

# ── 출력 방식 ──
with st.container(border=True):
    st.subheader("출력")

    out_mode = st.radio(
        "출력 방식",
        ["ZIP 다운로드", "폴더에 직접 저장"],
        horizontal=True,
    )

    if out_mode == "폴더에 직접 저장":
        col_out, col_outbtn = st.columns([5, 1])
        with col_out:
            out_dir_val = st.session_state.get("chunk_out_dir", "")
            out_dir_entered = st.text_input(
                "출력 폴더",
                value=out_dir_val,
                placeholder=r"C:\path\to\output_dir",
                label_visibility="collapsed",
            )
            st.session_state.chunk_out_dir = out_dir_entered.strip()
        with col_outbtn:
            if st.button("📁", use_container_width=True, help="폴더 선택"):
                d = pick_directory()
                if d:
                    st.session_state.chunk_out_dir = d
                    st.rerun()

st.write("")

# ── 실행 버튼 ──
run_btn = st.button("▶  청크 분할 실행", type="primary", use_container_width=True)

if run_btn:
    srt_path = st.session_state.chunk_srt_path
    error_msg = None

    if not srt_path:
        error_msg = "SRT 파일 경로를 입력하세요."
    elif not os.path.isfile(srt_path):
        error_msg = f"파일을 찾을 수 없습니다: `{srt_path}`"
    elif out_mode == "폴더에 직접 저장" and not st.session_state.get("chunk_out_dir", "").strip():
        error_msg = "출력 폴더를 지정하세요."

    if error_msg:
        st.error(error_msg)
    else:
        with st.spinner("SRT 파싱 중..."):
            raw = read_srt_text(srt_path)
            cues = parse_srt(raw) if raw else []

        if not cues:
            st.error("SRT 파싱 실패: 인코딩/형식을 확인하세요.")
        else:
            with st.spinner(f"{len(cues)}개 큐 분할 중..."):
                if split_mode == "시간 기준":
                    chunks = split_by_duration(cues, int(max_duration), int(overlap_sec))
                else:
                    chunks = split_by_chars(cues, int(max_chars), int(overlap_sec))

                base_name = os.path.splitext(os.path.basename(srt_path))[0]
                manifest, files = build_results(chunks, base_name)

            if out_mode == "폴더에 직접 저장":
                out_dir = st.session_state.chunk_out_dir
                os.makedirs(out_dir, exist_ok=True)
                for fn, txt in files.items():
                    with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
                        f.write(txt)
                manifest_path = os.path.join(out_dir, f"{base_name}.manifest.json")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)

            st.session_state.chunk_result = {
                "manifest": manifest,
                "files": files,
                "base_name": base_name,
                "cue_count": len(cues),
                "out_mode": out_mode,
                "out_dir": st.session_state.get("chunk_out_dir", ""),
            }
            st.rerun()

# ── 결과 표시 ──
if st.session_state.chunk_result:
    r = st.session_state.chunk_result
    manifest = r["manifest"]
    files = r["files"]

    st.divider()
    st.subheader("결과")

    col1, col2, col3 = st.columns(3)
    col1.metric("전체 큐 수", r["cue_count"])
    col2.metric("생성된 청크 수", len(manifest))
    total_chars = sum(m["char_count"] for m in manifest)
    col3.metric("총 글자 수", f"{total_chars:,}")

    st.write("")

    # 청크 목록 테이블
    import pandas as pd
    df = pd.DataFrame([
        {
            "청크": f"#{m['chunk_index']:03d}",
            "시작": m["start_hhmmss"],
            "종료": m["end_hhmmss"],
            "큐 수": m["cue_count"],
            "글자 수": f"{m['char_count']:,}",
            "파일명": m["file_txt"],
        }
        for m in manifest
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.write("")

    # 저장 완료 안내 or ZIP 다운로드
    if r["out_mode"] == "폴더에 직접 저장":
        st.success(f"✅ {len(manifest)}개 청크 + manifest.json 저장 완료: `{r['out_dir']}`")
        if st.button("📁 폴더 열기"):
            import subprocess
            subprocess.Popen(f'explorer "{r["out_dir"]}"')
    else:
        zip_bytes = make_zip(files, manifest, r["base_name"])
        st.download_button(
            label=f"⬇️  ZIP 다운로드 ({len(manifest)}개 청크 + manifest.json)",
            data=zip_bytes,
            file_name=f"{r['base_name']}_chunks.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary",
        )

    # 청크 미리보기
    st.write("")
    with st.expander("청크 내용 미리보기"):
        preview_idx = st.selectbox(
            "청크 선택",
            options=list(range(len(manifest))),
            format_func=lambda i: f"#{manifest[i]['chunk_index']:03d}  {manifest[i]['start_hhmmss']} ~ {manifest[i]['end_hhmmss']}  ({manifest[i]['cue_count']}큐)",
        )
        if preview_idx is not None:
            fn = manifest[preview_idx]["file_txt"]
            st.code(files[fn], language=None)
