"""Streamlit UI — 자동 자막 생성기"""

import streamlit as st
import threading
import queue
import os
import time
import traceback

from transcribe import run_caption_generation, build_files_info_split
from utils import pick_file

# ──────────────────────────────────────────────
# 페이지 설정 (반드시 첫 번째 Streamlit 호출)
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="자동 자막 생성기",
    page_icon="🎬",
    layout="centered",
)

# 멀티페이지 앱: 사이드바에 "SRT 전처리" 페이지가 자동으로 추가됨 (pages/ 디렉토리)

# ──────────────────────────────────────────────
# 세션 상태 초기화 (mutable default 버그 방지)
# ──────────────────────────────────────────────

if "job" not in st.session_state:
    st.session_state.job = None
if "single_path" not in st.session_state:
    st.session_state.single_path = ""
if "split_paths" not in st.session_state:
    st.session_state.split_paths = []
if "input_type" not in st.session_state:
    st.session_state.input_type = "통 영상"


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

VIDEO_FILETYPES = [("비디오 파일", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm"), ("모든 파일", "*.*")]
AUDIO_FILETYPES = [("오디오 파일", "*.mp3 *.wav *.m4a *.aac *.ogg *.flac"), ("모든 파일", "*.*")]


def worker(files_info, is_split, log_q, prog_q, cleanup, stop_event):
    """백그라운드 스레드: 자막 생성 파이프라인 실행."""
    try:
        srt_path = run_caption_generation(
            files_info=files_info,
            is_split=is_split,
            log_func=lambda msg: log_q.put(str(msg)),
            progress_func=lambda cur, tot: prog_q.put(("PROG", cur, tot)),
            cleanup=cleanup,
            stop_event=stop_event,
        )
        prog_q.put(("DONE", srt_path))
    except Exception as exc:
        log_q.put(traceback.format_exc())
        prog_q.put(("ERROR", str(exc)))


def drain_queues(job: dict):
    """큐에서 메시지를 소비하여 job 상태를 업데이트한다."""
    # 로그 큐 (최대 1000줄 유지)
    while True:
        try:
            job["logs"].append(job["log_q"].get_nowait())
            if len(job["logs"]) > 1000:
                job["logs"] = job["logs"][-1000:]
        except queue.Empty:
            break

    # 진행률 큐
    while True:
        try:
            item = job["prog_q"].get_nowait()
            tag = item[0]
            if tag == "PROG":
                cur, tot = item[1], item[2]
                job["prog_cur"] = cur
                job["prog_tot"] = tot
                if tot > 0:
                    job["progress"] = cur / tot
            elif tag == "DONE":
                job["status"] = "done"
                job["srt_path"] = item[1]
            elif tag == "ERROR":
                job["status"] = "error"
                job["error"] = item[1]
        except queue.Empty:
            break


def _clear_file_state():
    """입력 유형 변경 시 파일 선택 상태 초기화."""
    st.session_state.single_path = ""
    st.session_state.split_paths = []


# ──────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────

st.title("🎬 자동 자막 생성기")

# ── 입력 유형 ──
input_type = st.radio(
    "입력 유형",
    ["통 영상", "분할된 영상", "통 MP3", "분할된 MP3"],
    horizontal=True,
    index=["통 영상", "분할된 영상", "통 MP3", "분할된 MP3"].index(
        st.session_state.input_type
    ),
    on_change=_clear_file_state,
)
st.session_state.input_type = input_type

is_split = "분할" in input_type
is_audio = "MP3" in input_type
ftypes = AUDIO_FILETYPES if is_audio else VIDEO_FILETYPES

st.divider()

# ── 파일 선택 ──
with st.container(border=True):
    if not is_split:
        # 통 파일 모드
        col_input, col_btn = st.columns([5, 1])
        with col_input:
            entered = st.text_input(
                "파일 경로",
                value=st.session_state.single_path,
                placeholder=r"C:\path\to\video.mp4",
                label_visibility="collapsed",
            )
            st.session_state.single_path = entered.strip()
        with col_btn:
            if st.button("📂", use_container_width=True, help="파일 선택"):
                picked = pick_file(multiple=False, filetypes=ftypes)
                if picked:
                    st.session_state.single_path = picked
                    st.rerun()

        if st.session_state.single_path:
            p = st.session_state.single_path
            if os.path.isfile(p):
                size_mb = os.path.getsize(p) / (1024 ** 2)
                st.caption(f"✅ `{os.path.basename(p)}` ({size_mb:.1f} MB)")
            else:
                st.warning(f"❌ 파일을 찾을 수 없습니다: `{p}`")
        else:
            st.caption("파일 경로를 직접 입력하거나 📂 버튼으로 선택하세요.")

    else:
        # 분할 파일 모드
        col_add, col_clear = st.columns(2)
        with col_add:
            if st.button("📂 파일 추가", use_container_width=True):
                picked = pick_file(multiple=True, filetypes=ftypes)
                added = 0
                for p in picked:
                    if p and p not in st.session_state.split_paths:
                        st.session_state.split_paths.append(p)
                        added += 1
                if added:
                    st.toast(f"✅ {added}개 파일 추가됨")
                    st.rerun()
        with col_clear:
            if st.button("🗑️ 전체 지우기", use_container_width=True):
                st.session_state.split_paths = []
                st.rerun()

        paths = st.session_state.split_paths
        if paths:
            st.write(f"**{len(paths)}개 파일 선택됨**")
            for i, p in enumerate(paths):
                c1, c2 = st.columns([9, 1])
                with c1:
                    exists = os.path.isfile(p)
                    icon = "✅" if exists else "❌"
                    st.text(f"{icon} {i+1:02d}. {os.path.basename(p)}")
                with c2:
                    if st.button("✕", key=f"rm_{i}", help="제거"):
                        st.session_state.split_paths.pop(i)
                        st.rerun()
        else:
            st.caption("분할된 파트 파일들을 추가하세요.")

st.write("")

# ── 옵션 ──
cleanup = st.checkbox(
    "완료 후 임시 파일 자동 삭제 (분할 파트, WAV, 병합 파일)",
    value=False,
    help="자막 생성이 끝나면 중간 과정에서 만들어진 파일(분할 파트, 추출 WAV, 병합 파일)을 자동으로 삭제합니다. 원본 파일은 삭제되지 않습니다.",
)

# ── 실행 버튼 ──
job = st.session_state.job
is_running = job is not None and job.get("status") == "running"

col_start, col_cancel = st.columns([4, 1])
with col_start:
    start_btn = st.button(
        "▶  자막 생성 시작",
        use_container_width=True,
        type="primary",
        disabled=is_running,
    )
with col_cancel:
    cancel_btn = st.button(
        "■  취소",
        use_container_width=True,
        disabled=not is_running,
    )

# ── 시작 처리 ──
if start_btn and not is_running:
    error_msg = None
    files_info = None

    if is_split:
        paths = st.session_state.split_paths
        if not paths:
            error_msg = "처리할 파일을 선택하세요."
        else:
            missing = [p for p in paths if not os.path.isfile(p)]
            if missing:
                error_msg = "파일을 찾을 수 없습니다:\n" + "\n".join(missing)
            else:
                files_info = build_files_info_split(paths)
    else:
        p = st.session_state.single_path
        if not p:
            error_msg = "파일 경로를 입력하세요."
        elif not os.path.isfile(p):
            error_msg = f"파일을 찾을 수 없습니다: {p}"
        else:
            files_info = [{"path": p, "time_offset": 0.0, "part_num": 1, "total_parts": 1}]

    if error_msg:
        st.error(error_msg)
    else:
        log_q = queue.Queue()
        prog_q = queue.Queue()
        stop_event = threading.Event()

        # 이전 job 초기화 후 새 job 생성
        st.session_state.job = {
            "log_q": log_q,
            "prog_q": prog_q,
            "stop_event": stop_event,
            "logs": [],
            "progress": 0.0,
            "prog_cur": 0,
            "prog_tot": 0,
            "status": "running",
            "srt_path": None,
            "error": None,
        }

        t = threading.Thread(
            target=worker,
            args=(files_info, is_split, log_q, prog_q, cleanup, stop_event),
            daemon=True,
        )
        t.start()
        st.session_state.job["thread"] = t
        st.rerun()

# ── 취소 처리 ──
if cancel_btn and is_running:
    job["stop_event"].set()   # 스레드에 중단 신호
    job["status"] = "cancelled"
    st.rerun()

# ── 진행률 & 로그 표시 ──
if st.session_state.job is not None:
    job = st.session_state.job
    drain_queues(job)
    status = job["status"]

    # 진행률 바
    pct = int(job["progress"] * 100)
    cur = job.get("prog_cur", 0)
    tot = job.get("prog_tot", 0)
    chunk_info = f" | {cur}/{tot} 청크" if tot > 0 else ""

    if status == "running":
        st.progress(job["progress"], text=f"🔄 자막 생성 중... ({pct}%{chunk_info})")
    elif status == "done":
        st.progress(1.0, text="✅ 완료!")
    elif status in ("error", "cancelled"):
        st.progress(job["progress"], text="")

    # 상태 메시지
    if status == "done":
        st.success(f"SRT 저장 완료: `{job['srt_path']}`")
        if st.button("📁 출력 폴더 열기"):
            import subprocess
            subprocess.Popen(f'explorer /select,"{job["srt_path"]}"')
    elif status == "error":
        st.error(f"❌ 오류: {job['error']}")
        with st.expander("상세 오류 보기"):
            st.code("\n".join(job["logs"][-50:]), language=None)
    elif status == "cancelled":
        srt = job.get("srt_path")
        if srt and os.path.isfile(srt):
            st.warning(f"⚠️ 취소됨. 부분 SRT 저장됨: `{srt}`")
        else:
            st.warning("⚠️ 취소되었습니다.")

    # 로그 패널
    if job["logs"]:
        with st.expander("📋 처리 로그", expanded=(status == "running")):
            log_text = "\n".join(job["logs"][-300:])
            st.code(log_text, language=None)

    # 실행 중이면 0.5초 후 rerun → 실시간 업데이트
    if status == "running":
        time.sleep(0.5)
        st.rerun()
