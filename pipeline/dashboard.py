"""Chzzk 파이프라인 대시보드 — 실시간 로그 + 현재 상태 + 설정 진입점.

설계 원칙:
- 파이프라인 프로세스와 IPC 없음. output/logs/pipeline.log 를 incremental tail 하고
  output/pipeline_state.json 을 주기 폴링해서 표시만 함. 라이트웨이트.
- tkinter + ttk. Windows 11 네이티브 느낌을 위해 sv-ttk 적용, 미설치 시 기본 테마 폴백.
- 트레이 앱에서 `open_dashboard()` 로 호출. 중복 호출 시 기존 창을 포커스.

탭:
1. 실시간 로그 — 색상 레벨 매칭, 필터(ALL/INFO/WARN/ERROR), 자동 스크롤 토글
2. 현재 상태 — 처리 중 VOD / 최근 완료 / 에러 요약 + 리포트 더블클릭 → 브라우저 오픈
3. 설정 — 기존 settings_ui.open_settings() 호출 버튼 (별도 모달)
"""
from __future__ import annotations

import json
import os
import re
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from typing import Optional

try:
    import sv_ttk  # type: ignore[import-untyped]

    _HAS_SV_TTK = True
except ImportError:
    _HAS_SV_TTK = False

_LOG_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")
_LEVEL_COLORS = {
    "DEBUG": "#7a7a7a",
    "INFO": "#3c9fe8",
    "WARNING": "#e8a33c",
    "ERROR": "#e85c5c",
    "CRITICAL": "#ff3d3d",
}
_LEVEL_FILTERS = ("ALL", "INFO+", "WARNING+", "ERROR")
_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

_STATUS_LABELS = {
    "queued": "대기",
    "downloading": "다운로드 중",
    "transcribing": "자막 생성 중",
    "summarizing": "요약 중",
    "completed": "완료",
    "error": "에러",
}
_STATUS_COLORS = {
    "queued": "#7a7a7a",
    "downloading": "#3c9fe8",
    "transcribing": "#9f7fe8",
    "summarizing": "#e8a33c",
    "completed": "#4caf50",
    "error": "#e85c5c",
}


class _LogTail:
    """파일을 incremental 로 읽어 콜백에 청크 단위로 넘김."""

    def __init__(self, path: Path, on_lines):
        self.path = path
        self.on_lines = on_lines
        self._offset = 0
        self._inode: Optional[int] = None

    def poll(self) -> None:
        if not self.path.exists():
            return
        try:
            st = self.path.stat()
        except OSError:
            return

        inode = (st.st_dev, st.st_ino)
        if self._inode is not None and inode != self._inode:
            # 로테이션 감지 → 처음부터
            self._offset = 0
        self._inode = inode

        if st.st_size < self._offset:
            # 트렁케이트
            self._offset = 0

        if st.st_size == self._offset:
            return

        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                chunk = f.read()
                self._offset = f.tell()
        except OSError:
            return

        if chunk:
            lines = chunk.splitlines()
            self.on_lines(lines)

    def load_tail(self, max_bytes: int = 64 * 1024) -> list[str]:
        """창 열릴 때 최근 max_bytes 를 한 번에 표시."""
        if not self.path.exists():
            return []
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        start = max(0, size - max_bytes)
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(start)
                if start > 0:
                    f.readline()  # 부분 라인 폐기
                lines = f.read().splitlines()
                self._offset = f.tell()
                try:
                    st = self.path.stat()
                    self._inode = (st.st_dev, st.st_ino)
                except OSError:
                    pass
                return lines
        except OSError:
            return []


class Dashboard:
    """메인 대시보드 창 (싱글톤 — open_dashboard() 에서 재사용)."""

    _instance: Optional["Dashboard"] = None

    @classmethod
    def open(cls, cfg: Optional[dict] = None) -> "Dashboard":
        if cls._instance is not None and cls._instance._alive:
            cls._instance.focus()
            return cls._instance
        inst = cls(cfg=cfg)
        cls._instance = inst
        inst.run()
        return inst

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or {}
        self.project_root = Path(__file__).resolve().parent.parent
        self.log_path = Path(self.cfg.get("output_dir", "./output")) / "logs" / "pipeline.log"
        self.state_path = Path(self.cfg.get("output_dir", "./output")) / "pipeline_state.json"
        self._alive = False
        self._auto_scroll = True
        self._filter = "ALL"
        self.root: Optional[tk.Tk] = None
        self.log_widget: Optional[tk.Text] = None
        self.status_tree: Optional[ttk.Treeview] = None
        self.report_tree: Optional[ttk.Treeview] = None
        self.header_label: Optional[ttk.Label] = None
        self._tail: Optional[_LogTail] = None
        self._cost_tree: Optional[ttk.Treeview] = None
        self._breakdown_tree: Optional[ttk.Treeview] = None
        self._model_status: Optional[ttk.Label] = None
        self._stats_summary: Optional[ttk.Label] = None

    # ---------- 라이프사이클 ----------
    def run(self) -> None:
        self.root = tk.Tk()
        self.root.title("Chzzk VOD 파이프라인 — 대시보드")
        self.root.geometry("1000x680")
        self.root.minsize(820, 520)

        if _HAS_SV_TTK:
            try:
                sv_ttk.set_theme("dark")
            except Exception:  # noqa: BLE001
                pass

        self._build_layout()
        self._alive = True
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 초기 로그 tail 로드
        self._tail = _LogTail(self.log_path, on_lines=self._append_log_lines)
        initial = self._tail.load_tail()
        if initial:
            self._append_log_lines(initial)
        else:
            self._append_log_lines(["[로그 파일이 아직 없거나 비어있습니다 — 파이프라인 실행 후 자동으로 표시됩니다]"])

        self._poll_log()
        self._poll_status()

        self.root.mainloop()

    def focus(self) -> None:
        if self.root is None:
            return
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        self._alive = False
        if self.root is not None:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
        Dashboard._instance = None

    # ---------- 레이아웃 ----------
    def _build_layout(self) -> None:
        assert self.root is not None

        # 상단 헤더 — 간단 상태 요약
        header = ttk.Frame(self.root, padding=(16, 10, 16, 6))
        header.pack(fill="x")
        title = ttk.Label(
            header, text="Chzzk VOD 파이프라인", font=("Segoe UI", 14, "bold")
        )
        title.pack(side="left")
        self.header_label = ttk.Label(header, text="상태 확인 중…", foreground="#7a7a7a")
        self.header_label.pack(side="right")

        # Notebook (탭)
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self._build_log_tab(nb)
        self._build_status_tab(nb)
        self._build_cost_tab(nb)
        self._build_settings_tab(nb)

    def _build_log_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=8)
        nb.add(frame, text="  실시간 로그  ")

        # 컨트롤 바
        ctrl = ttk.Frame(frame)
        ctrl.pack(fill="x", pady=(0, 6))

        ttk.Label(ctrl, text="필터:").pack(side="left", padx=(0, 6))
        self._filter_var = tk.StringVar(value=self._filter)
        filter_combo = ttk.Combobox(
            ctrl,
            textvariable=self._filter_var,
            values=_LEVEL_FILTERS,
            state="readonly",
            width=10,
        )
        filter_combo.pack(side="left")
        filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_filter_change())

        self._auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ctrl,
            text="자동 스크롤",
            variable=self._auto_scroll_var,
            command=self._on_autoscroll_toggle,
        ).pack(side="left", padx=(14, 0))

        ttk.Button(ctrl, text="지우기", command=self._clear_log, width=8).pack(
            side="right"
        )
        ttk.Button(
            ctrl, text="로그 파일 열기", command=self._open_log_file, width=16
        ).pack(side="right", padx=(0, 6))

        # 로그 Text + 스크롤바
        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True)

        self.log_widget = tk.Text(
            wrap,
            wrap="none",
            font=("Consolas", 10),
            bg="#1a1b26",
            fg="#c0caf5",
            insertbackground="#c0caf5",
            relief="flat",
            padx=8,
            pady=6,
        )
        self.log_widget.pack(side="left", fill="both", expand=True)

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.log_widget.yview)
        vsb.pack(side="right", fill="y")
        self.log_widget.config(yscrollcommand=vsb.set)

        # 레벨 태그
        for level, color in _LEVEL_COLORS.items():
            self.log_widget.tag_config(level, foreground=color)

        self.log_widget.config(state="disabled")

    def _build_status_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=12)
        nb.add(frame, text="  현재 상태  ")

        # 처리 중 섹션
        active_group = ttk.LabelFrame(frame, text="진행 중 / 최근 업데이트", padding=10)
        active_group.pack(fill="x", pady=(0, 10))

        cols = ("key", "status", "updated", "info")
        self.status_tree = ttk.Treeview(
            active_group, columns=cols, show="headings", height=8
        )
        self.status_tree.heading("key", text="VOD")
        self.status_tree.heading("status", text="단계")
        self.status_tree.heading("updated", text="최근 갱신")
        self.status_tree.heading("info", text="비고")
        self.status_tree.column("key", width=260)
        self.status_tree.column("status", width=110, anchor="center")
        self.status_tree.column("updated", width=150, anchor="center")
        self.status_tree.column("info", width=360)
        self.status_tree.pack(fill="x", expand=False)

        # 리포트 섹션
        reports_group = ttk.LabelFrame(frame, text="완료 리포트 (더블클릭 → 브라우저)", padding=10)
        reports_group.pack(fill="both", expand=True)

        rcols = ("title", "updated", "path")
        self.report_tree = ttk.Treeview(
            reports_group, columns=rcols, show="headings"
        )
        self.report_tree.heading("title", text="리포트")
        self.report_tree.heading("updated", text="완료 시각")
        self.report_tree.heading("path", text="경로")
        self.report_tree.column("title", width=360)
        self.report_tree.column("updated", width=150, anchor="center")
        self.report_tree.column("path", width=420)
        self.report_tree.pack(fill="both", expand=True)
        self.report_tree.bind("<Double-1>", self._on_report_dblclick)

        # 진행 상태 트리 우클릭 메뉴
        self.status_tree.bind("<Button-3>", self._on_status_rightclick)
        self.status_tree.bind("<Double-1>", self._on_status_dblclick)

    def _build_cost_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=16)
        nb.add(frame, text="  모델 & 비용  ")

        # ---- 모델 선택 ----
        model_group = ttk.LabelFrame(frame, text="Claude 모델 선택", padding=12)
        model_group.pack(fill="x", pady=(0, 12))

        ttk.Label(
            model_group,
            text="변경 후 [저장] 버튼을 누르면 다음 VOD 처리부터 적용됩니다.",
            foreground="#8a8a8a",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        self._model_var = tk.StringVar(value=self.cfg.get("claude_model", "") or "")
        models = [
            ("CLI 기본", ""),
            ("Haiku (경량·저가)", "haiku"),
            ("Sonnet (기본·균형)", "sonnet"),
            ("Opus (최고 품질)", "opus"),
        ]
        for i, (label, value) in enumerate(models):
            ttk.Radiobutton(
                model_group,
                text=label,
                variable=self._model_var,
                value=value,
                command=self._on_model_select,
            ).grid(row=1, column=i, sticky="w", padx=(0, 16))

        self._model_status = ttk.Label(model_group, text="", foreground="#8a8a8a")
        self._model_status.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))

        ttk.Button(
            model_group, text="저장", command=self._save_model_choice, width=12
        ).grid(row=1, column=4, sticky="e", padx=(24, 0))

        # ---- 실측 사용량 ----
        stats_group = ttk.LabelFrame(
            frame, text="실측 사용량 (pipeline.log 의 Claude usage 기록)", padding=12
        )
        stats_group.pack(fill="x", pady=(0, 12))
        self._stats_summary = ttk.Label(
            stats_group, text="로그 분석 중…", font=("Segoe UI", 10)
        )
        self._stats_summary.pack(anchor="w")

        # ---- 모델별 예상 비용 표 ----
        proj_group = ttk.LabelFrame(
            frame, text="모델별 예상 비용 (현재까지의 토큰 workload 동일 가정)", padding=12
        )
        proj_group.pack(fill="both", expand=True)

        cols = ("model", "per_call", "total", "vs_actual")
        self._cost_tree = ttk.Treeview(
            proj_group, columns=cols, show="headings", height=4
        )
        self._cost_tree.heading("model", text="모델")
        self._cost_tree.heading("per_call", text="호출 1회 평균")
        self._cost_tree.heading("total", text="누적 총합")
        self._cost_tree.heading("vs_actual", text="실측 대비")
        self._cost_tree.column("model", width=200)
        self._cost_tree.column("per_call", width=160, anchor="e")
        self._cost_tree.column("total", width=160, anchor="e")
        self._cost_tree.column("vs_actual", width=160, anchor="e")
        self._cost_tree.pack(fill="both", expand=True)

        # 참고 주석
        ttk.Label(
            frame,
            text=(
                "참고: USD/1M tokens 기준 Haiku $1/$5 · Sonnet $3/$15 · Opus $15/$75. "
                "캐시는 write 1.25× / read 0.10× (Anthropic 규칙). "
                "가격 drift 시 pipeline/cost_estimator.py:PRICING 갱신."
            ),
            foreground="#7a7a7a",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        # ---- VOD별 breakdown ----
        breakdown_group = ttk.LabelFrame(
            frame, text="VOD별 비용 (로그 경계 기준 실측)", padding=12
        )
        breakdown_group.pack(fill="both", expand=True, pady=(12, 0))

        bcols = ("vod", "title", "calls", "tokens", "actual", "projection")
        self._breakdown_tree = ttk.Treeview(
            breakdown_group, columns=bcols, show="headings", height=8
        )
        self._breakdown_tree.heading("vod", text="VOD")
        self._breakdown_tree.heading("title", text="제목")
        self._breakdown_tree.heading("calls", text="호출")
        self._breakdown_tree.heading("tokens", text="in/out 토큰")
        self._breakdown_tree.heading("actual", text="실측 비용")
        self._breakdown_tree.heading("projection", text="Haiku / Sonnet / Opus")
        self._breakdown_tree.column("vod", width=100)
        self._breakdown_tree.column("title", width=280)
        self._breakdown_tree.column("calls", width=60, anchor="e")
        self._breakdown_tree.column("tokens", width=130, anchor="e")
        self._breakdown_tree.column("actual", width=100, anchor="e")
        self._breakdown_tree.column("projection", width=240, anchor="e")
        self._breakdown_tree.pack(fill="both", expand=True)

        ttk.Button(
            frame, text="다시 계산", command=self._refresh_cost_tab, width=14
        ).pack(anchor="e", pady=(8, 0))

        # 초기 렌더
        self._refresh_cost_tab()

    def _on_model_select(self) -> None:
        if hasattr(self, "_model_status") and self._model_status is not None:
            choice = self._model_var.get() or "CLI 기본"
            self._model_status.config(text=f"선택: {choice} (저장 시 반영)")

    def _save_model_choice(self) -> None:
        from pipeline.config import load_config, save_config

        chosen = self._model_var.get()
        try:
            cfg = load_config()
            cfg["claude_model"] = chosen
            save_config(cfg)
            self.cfg = cfg
            display = chosen or "CLI 기본"
            if self._model_status is not None:
                self._model_status.config(
                    text=f"✓ 저장됨: {display} — 다음 VOD 처리부터 적용"
                )
            self._header_flash(f"모델 저장: {display}")
        except Exception as e:  # noqa: BLE001
            if self._model_status is not None:
                self._model_status.config(text=f"저장 실패: {e}")

    def _refresh_cost_tab(self) -> None:
        from pipeline.cost_estimator import (
            UsageStats,
            aggregate,
            estimate_cost,
            estimate_per_call,
            format_tokens,
            format_usd,
            parse_log_file,
            PRICING,
        )

        calls = parse_log_file(self.log_path)
        stats = aggregate(calls)

        if stats.calls == 0:
            self._stats_summary.config(
                text="기록된 Claude API 호출이 없습니다. VOD 를 최소 1개 처리한 뒤 [다시 계산]."
            )
            if self._cost_tree is not None:
                self._cost_tree.delete(*self._cost_tree.get_children())
            return

        summary = (
            f"총 호출: {stats.calls}  ·  "
            f"input: {format_tokens(stats.input_tokens)}  "
            f"output: {format_tokens(stats.output_tokens)}  "
            f"cache write: {format_tokens(stats.cache_write_tokens)}  "
            f"cache read: {format_tokens(stats.cache_read_tokens)}  ·  "
            f"실측 누적: {format_usd(stats.actual_cost_usd)}"
        )
        self._stats_summary.config(text=summary)

        if self._cost_tree is None:
            return
        self._cost_tree.delete(*self._cost_tree.get_children())
        actual = stats.actual_cost_usd
        for model in ("haiku", "sonnet", "opus"):
            per = estimate_per_call(stats, model)
            total = estimate_cost(stats, model)
            if actual > 0:
                ratio = total / actual
                vs = f"{ratio:.2f}×"
            else:
                vs = "-"
            self._cost_tree.insert(
                "",
                "end",
                values=(
                    f"{model.capitalize()}  (in ${PRICING[model]['input']:.2f} / out ${PRICING[model]['output']:.2f} per 1M)",
                    format_usd(per),
                    format_usd(total),
                    vs,
                ),
            )

        # VOD별 breakdown
        if self._breakdown_tree is not None:
            from pipeline.vod_log_index import index_vods_from_log

            entries = index_vods_from_log(self.log_path)
            self._breakdown_tree.delete(*self._breakdown_tree.get_children())
            # 최근순
            entries_sorted = list(reversed(entries))
            for e in entries_sorted[:50]:
                if not e.calls:
                    continue
                e_stats = UsageStats(
                    calls=len(e.calls),
                    input_tokens=e.total_input,
                    output_tokens=e.total_output,
                    cache_write_tokens=e.total_cache_write,
                    cache_read_tokens=e.total_cache_read,
                    actual_cost_usd=e.actual_cost_usd,
                )
                haiku = estimate_cost(e_stats, "haiku")
                sonnet = estimate_cost(e_stats, "sonnet")
                opus = estimate_cost(e_stats, "opus")
                self._breakdown_tree.insert(
                    "",
                    "end",
                    values=(
                        e.video_no,
                        e.title[:60],
                        len(e.calls),
                        f"{format_tokens(e.total_input)} / {format_tokens(e.total_output)}",
                        format_usd(e.actual_cost_usd),
                        f"{format_usd(haiku)} / {format_usd(sonnet)} / {format_usd(opus)}",
                    ),
                )

    def _build_settings_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb, padding=24)
        nb.add(frame, text="  설정  ")

        ttk.Label(
            frame,
            text="상세 설정은 별도 창에서 편집합니다.",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            frame,
            text="저장 시 다음 폴링 주기부터 자동 반영됩니다.",
            foreground="#8a8a8a",
        ).pack(anchor="w", pady=(0, 16))

        btn_row = ttk.Frame(frame)
        btn_row.pack(anchor="w")
        ttk.Button(
            btn_row,
            text="설정 창 열기",
            command=self._open_settings,
            width=20,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            btn_row,
            text="설정 파일 직접 편집",
            command=self._open_config_file,
            width=20,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            btn_row,
            text="쿠키 새로고침",
            command=self._refresh_cookies,
            width=20,
        ).pack(side="left")

    # ---------- 로그 ----------
    def _append_log_lines(self, lines: list[str]) -> None:
        if self.log_widget is None:
            return
        self.log_widget.config(state="normal")
        for line in lines:
            level = _detect_level(line)
            if not _passes_filter(level, self._filter):
                continue
            self.log_widget.insert("end", line + "\n", level)
        if self._auto_scroll_var.get():
            self.log_widget.see("end")
        self.log_widget.config(state="disabled")

    def _on_filter_change(self) -> None:
        self._filter = self._filter_var.get()
        # 현재 버퍼 재필터링 대신 파일 tail 을 재로드
        if self.log_widget is None or self._tail is None:
            return
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.config(state="disabled")
        self._tail._offset = 0
        initial = self._tail.load_tail()
        if initial:
            self._append_log_lines(initial)

    def _on_autoscroll_toggle(self) -> None:
        self._auto_scroll = self._auto_scroll_var.get()

    def _clear_log(self) -> None:
        if self.log_widget is None:
            return
        self.log_widget.config(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.config(state="disabled")

    def _open_log_file(self) -> None:
        if self.log_path.exists() and os.name == "nt":
            os.startfile(str(self.log_path))  # type: ignore[attr-defined]

    def _poll_log(self) -> None:
        if not self._alive or self.root is None:
            return
        if self._tail is not None:
            try:
                self._tail.poll()
            except Exception:  # noqa: BLE001
                pass
        self.root.after(700, self._poll_log)

    # ---------- 상태 ----------
    def _poll_status(self) -> None:
        if not self._alive or self.root is None:
            return
        threading.Thread(target=self._refresh_status_bg, daemon=True).start()
        self.root.after(2500, self._poll_status)

    def _refresh_status_bg(self) -> None:
        try:
            data = self._read_state()
            reports = self._scan_reports()
        except Exception:  # noqa: BLE001
            return
        if self.root is None:
            return
        self.root.after(0, lambda: self._apply_status(data, reports))

    def _read_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _scan_reports(self) -> list[dict]:
        out = Path(self.cfg.get("output_dir", "./output"))
        if not out.is_dir():
            return []
        items = []
        for html in out.glob("*.html"):
            try:
                mtime = html.stat().st_mtime
            except OSError:
                continue
            items.append(
                {
                    "title": html.stem,
                    "mtime": mtime,
                    "path": str(html.resolve()),
                }
            )
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items[:50]

    def _apply_status(self, state: dict, reports: list[dict]) -> None:
        if self.status_tree is None or self.report_tree is None or self.header_label is None:
            return

        processed = state.get("processed_vods", {}) or {}
        active = [
            (k, v) for k, v in processed.items()
            if v.get("status") not in ("completed",)
        ]
        # 최근 업데이트 순
        active.sort(key=lambda kv: kv[1].get("updated_at", ""), reverse=True)
        active = active[:20]

        # 헤더 요약
        status_counts: dict[str, int] = {}
        for _, v in processed.items():
            s = v.get("status", "?")
            status_counts[s] = status_counts.get(s, 0) + 1
        summary = " · ".join(
            f"{_STATUS_LABELS.get(k, k)} {n}" for k, n in sorted(status_counts.items())
        ) or "처리 이력 없음"
        self.header_label.config(text=summary)

        # Active tree 갱신
        self.status_tree.delete(*self.status_tree.get_children())
        for key, v in active:
            status = v.get("status", "?")
            label = _STATUS_LABELS.get(status, status)
            updated = _short_ts(v.get("updated_at", ""))
            info = v.get("error") or v.get("video_no") or ""
            row = self.status_tree.insert(
                "",
                "end",
                values=(key, label, updated, info),
                tags=(status,),
            )
            color = _STATUS_COLORS.get(status)
            if color:
                self.status_tree.tag_configure(status, foreground=color)
            del row

        # Reports tree 갱신
        self.report_tree.delete(*self.report_tree.get_children())
        import datetime

        for r in reports:
            ts = datetime.datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M")
            self.report_tree.insert(
                "", "end", values=(r["title"], ts, r["path"])
            )

    def _on_status_rightclick(self, event) -> None:
        if self.status_tree is None or self.root is None:
            return
        row = self.status_tree.identify_row(event.y)
        if not row:
            return
        self.status_tree.selection_set(row)
        values = self.status_tree.item(row, "values")
        if len(values) < 2:
            return
        key, label = values[0], values[1]
        status = _reverse_status_label(label)
        info = values[3] if len(values) > 3 else ""

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label="재처리", command=lambda: self._action_reprocess(key)
        )
        if status == "error" or status == "?":
            menu.add_command(
                label="에러 상세 보기", command=lambda: self._show_error_details(key, info)
            )
        if status == "completed":
            menu.add_command(
                label="리포트 열기", command=lambda: self._open_report_for(key)
            )
        menu.add_separator()
        menu.add_command(
            label="상태에서 제거", command=lambda: self._remove_from_state(key)
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_status_dblclick(self, _event) -> None:
        if self.status_tree is None:
            return
        sel = self.status_tree.selection()
        if not sel:
            return
        values = self.status_tree.item(sel[0], "values")
        if len(values) < 2:
            return
        key, label = values[0], values[1]
        status = _reverse_status_label(label)
        info = values[3] if len(values) > 3 else ""
        if status == "completed":
            self._open_report_for(key)
        elif status == "error":
            self._show_error_details(key, info)

    def _action_reprocess(self, key: str) -> None:
        """특정 VOD 를 python -m pipeline.main --process <video_no> 로 재처리."""
        import subprocess
        import sys as _sys

        video_no = key.split(":", 1)[-1] if ":" in key else key
        try:
            creationflags = 0
            if _sys.platform == "win32":
                creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            subprocess.Popen(
                [_sys.executable, "-m", "pipeline.main", "--process", video_no],
                cwd=str(self.project_root),
                creationflags=creationflags,
                close_fds=True,
            )
            self._header_flash(f"재처리 요청: {video_no}")
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"재처리 실패: {e}")

    def _open_report_for(self, key: str) -> None:
        state = self._read_state()
        entry = state.get("processed_vods", {}).get(key, {})
        html = entry.get("output_html")
        if not html:
            self._header_flash(f"리포트 없음: {key}")
            return
        try:
            webbrowser.open(Path(html).resolve().as_uri())
        except Exception:  # noqa: BLE001
            pass

    def _remove_from_state(self, key: str) -> None:
        state_path = self.state_path
        if not state_path.exists():
            return
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if key in data.get("processed_vods", {}):
                del data["processed_vods"][key]
                tmp = state_path.with_suffix(state_path.suffix + ".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, state_path)
                self._header_flash(f"상태 제거: {key}")
                # 즉시 리프레시
                threading.Thread(target=self._refresh_status_bg, daemon=True).start()
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"제거 실패: {e}")

    def _show_error_details(self, key: str, brief: str) -> None:
        """팝업 창에 해당 VOD 관련 로그 tail 을 표시."""
        if self.root is None:
            return
        win = tk.Toplevel(self.root)
        win.title(f"에러 상세 — {key}")
        win.geometry("820x520")

        ttk.Label(win, text=f"VOD: {key}", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(12, 2)
        )
        if brief:
            ttk.Label(win, text=f"요약: {brief}", foreground="#e85c5c").pack(
                anchor="w", padx=12, pady=(0, 8)
            )

        txt = tk.Text(
            win,
            wrap="none",
            font=("Consolas", 9),
            bg="#1a1b26",
            fg="#c0caf5",
            padx=8,
            pady=6,
        )
        vsb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True, padx=(12, 0), pady=(0, 8))

        # 해당 VOD 번호를 포함한 로그 라인만 필터 (최근 300라인)
        video_no = key.split(":", 1)[-1] if ":" in key else key
        matched = _grep_log_for_vod(self.log_path, video_no, limit=300)
        if not matched:
            txt.insert("end", "이 VOD 와 관련된 로그 라인을 찾을 수 없습니다.\n")
        else:
            for level_tag, line in matched:
                txt.insert("end", line + "\n", level_tag)
        for lvl, color in _LEVEL_COLORS.items():
            txt.tag_config(lvl, foreground=color)
        txt.config(state="disabled")

        btnbar = ttk.Frame(win)
        btnbar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(
            btnbar,
            text="클립보드 복사",
            command=lambda: _copy_to_clipboard(self.root, txt.get("1.0", "end")),
        ).pack(side="left")
        ttk.Button(btnbar, text="닫기", command=win.destroy).pack(side="right")

    def _on_report_dblclick(self, _event) -> None:
        if self.report_tree is None:
            return
        sel = self.report_tree.selection()
        if not sel:
            return
        values = self.report_tree.item(sel[0], "values")
        if len(values) >= 3:
            path = values[2]
            try:
                webbrowser.open(Path(path).as_uri())
            except Exception:  # noqa: BLE001
                pass

    # ---------- 설정 ----------
    def _open_settings(self) -> None:
        try:
            from pipeline.settings_ui import open_settings

            def _on_save(new_cfg):
                self.cfg = new_cfg

            open_settings(on_save=_on_save)
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"설정 창 실패: {e}")

    def _open_config_file(self) -> None:
        from pipeline.config import _resolve_config_path

        path = _resolve_config_path(None)
        if path.exists() and os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]

    def _refresh_cookies(self) -> None:
        try:
            from pipeline.cookie_refresh import refresh_cookies

            ok, reason = refresh_cookies()
            self._header_flash(("✓ " if ok else "✗ ") + reason)
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"쿠키 갱신 실패: {e}")

    def _header_flash(self, msg: str) -> None:
        if self.header_label is None or self.root is None:
            return
        original = self.header_label.cget("text")
        self.header_label.config(text=msg, foreground="#3c9fe8")
        self.root.after(
            4000,
            lambda: self.header_label
            and self.header_label.config(text=original, foreground="#7a7a7a"),
        )


# ---------- 헬퍼 ----------
def _detect_level(line: str) -> str:
    m = _LOG_LEVEL_RE.search(line)
    return m.group(1) if m else "INFO"


def _passes_filter(level: str, flt: str) -> bool:
    if flt == "ALL":
        return True
    if flt == "INFO+":
        return _LEVEL_ORDER.get(level, 1) >= 1
    if flt == "WARNING+":
        return _LEVEL_ORDER.get(level, 1) >= 2
    if flt == "ERROR":
        return _LEVEL_ORDER.get(level, 1) >= 3
    return True


_STATUS_LABEL_INVERSE = {v: k for k, v in _STATUS_LABELS.items()}


def _reverse_status_label(label: str) -> str:
    return _STATUS_LABEL_INVERSE.get(label, "?")


def _grep_log_for_vod(log_path: Path, video_no: str, limit: int = 300) -> list[tuple[str, str]]:
    """log 에서 video_no 를 포함하는 라인 최근 limit 개 반환. (level_tag, line) 튜플."""
    if not log_path.exists() or not video_no:
        return []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [ln.rstrip() for ln in f if video_no in ln]
    except OSError:
        return []
    lines = lines[-limit:]
    return [(_detect_level(ln), ln) for ln in lines]


def _copy_to_clipboard(root, text: str) -> None:
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    except Exception:  # noqa: BLE001
        pass


def _short_ts(iso: str) -> str:
    if not iso:
        return ""
    # "2026-04-17T22:17:15.331976+09:00" → "04-17 22:17"
    try:
        import datetime

        dt = datetime.datetime.fromisoformat(iso)
        return dt.strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso[:16]


def open_dashboard(cfg: Optional[dict] = None) -> None:
    """외부 호출 진입점 (트레이에서 사용)."""
    Dashboard.open(cfg=cfg)


def main() -> int:
    from pipeline._io_encoding import force_utf8_stdio
    from pipeline.config import load_config

    force_utf8_stdio()
    cfg = load_config()
    open_dashboard(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
