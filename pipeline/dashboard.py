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
    "skipped_bootstrap": "스킵 (bootstrap)",
    "skipped_user": "스킵 (사용자)",
}
_STATUS_COLORS = {
    "queued": "#7a7a7a",
    "downloading": "#3c9fe8",
    "transcribing": "#9f7fe8",
    "summarizing": "#e8a33c",
    "completed": "#4caf50",
    "error": "#e85c5c",
    "skipped_bootstrap": "#9aa1b3",
    "skipped_user": "#9aa1b3",
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
        out_dir = Path(self.cfg.get("output_dir", "./output"))
        self.log_path = out_dir / "logs" / "pipeline.log"
        self.log_dir = str(out_dir / "logs")
        self.state_path = out_dir / "pipeline_state.json"
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
        self._trend_canvas: Optional[tk.Canvas] = None
        self._trend_summary: Optional[ttk.Label] = None
        self._model_status: Optional[ttk.Label] = None
        self._stats_summary: Optional[ttk.Label] = None
        self._settings_win = None  # SettingsWindow 인스턴스 (중복 열림 방지)

        # 데몬: 대시보드 프로세스가 직접 소유. 이전의 tray_app.py + control.py
        # 파일 IPC 를 대체. 창이 닫히면 self._on_close 에서 stop() 한다.
        from pipeline.state import PipelineState
        from pipeline.daemon import PipelineDaemon

        self.state = PipelineState(str(self.state_path))
        self.daemon = PipelineDaemon(
            cfg=self.cfg,
            state=self.state,
            log_dir=self.log_dir,
            notify=self._notify,
        )

        # 데몬: 대시보드 프로세스가 직접 소유. 이전의 tray_app.py + control.py
        # 파일 IPC 를 대체. 창이 닫히면 self._on_close 에서 stop() 한다.
        from pipeline.state import PipelineState
        from pipeline.daemon import PipelineDaemon

        self.state = PipelineState(str(self.state_path))
        self.daemon = PipelineDaemon(
            cfg=self.cfg,
            state=self.state,
            log_dir=self.log_dir,
            notify=self._notify,
        )

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

        # 데몬은 GUI 가 뜬 뒤 시작 — 초기화 에러가 있으면 로그에 찍히고
        # 사용자는 창에서 바로 확인할 수 있다.
        try:
            self.daemon.start()
        except Exception as e:  # noqa: BLE001
            self._append_log_lines([f"[데몬 시작 실패] {e}"])

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
        # 데몬을 먼저 정지 — 현재 처리 중인 VOD 가 있으면 안전하게 마무리할 수
        # 있도록 최대 5초 대기. 사용자가 응답 지연을 느끼면 두 번째 닫기에서
        # 프로세스가 어차피 종료되므로 딱히 추가 강제 종료는 하지 않는다.
        try:
            self.daemon.stop(timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
        if self.root is not None:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
        Dashboard._instance = None

    def _notify(self, title: str, message: str) -> None:
        """데몬이 GUI 에 띄우는 가벼운 알림. 현재는 로그창에 기록."""
        try:
            self._append_log_lines([f"[알림] {title}: {message}"])
        except Exception:  # noqa: BLE001
            pass

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

        # 상단 툴바 — 수동 처리 + 오류 일괄 제거
        toolbar = ttk.Frame(active_group)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(
            toolbar,
            text="우클릭: 단일 엔트리 액션 · 더블클릭: 리포트/에러 상세",
            foreground="#7a86a8",
        ).pack(side="left")
        ttk.Button(
            toolbar,
            text="오류 기록 일괄 제거",
            command=self._clear_all_errors,
            width=20,
        ).pack(side="right")
        ttk.Button(
            toolbar,
            text="+ 수동 VOD 처리",
            command=self._open_manual_process_dialog,
            width=18,
        ).pack(side="right", padx=(0, 6))

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
        self.report_tree.bind("<Button-3>", self._on_report_rightclick)

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

        # ---- 최근 14일 트렌드 ----
        trend_group = ttk.LabelFrame(
            frame, text="최근 14일 비용 트렌드 (실측 USD)", padding=12
        )
        trend_group.pack(fill="x", pady=(0, 12))
        self._trend_canvas = tk.Canvas(
            trend_group,
            height=140,
            highlightthickness=0,
            background="#1a1b26",
        )
        self._trend_canvas.pack(fill="x", expand=True)
        self._trend_canvas.bind("<Configure>", lambda _e: self._render_trend_chart())
        self._trend_summary = ttk.Label(
            trend_group, text="", foreground="#8a8a8a"
        )
        self._trend_summary.pack(anchor="w", pady=(6, 0))

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
        """비용 탭 재계산.

        `parse_log_file` / `index_vods_from_log` 는 pipeline.log 전체를 훑어
        파일 크기에 비례해 UI 스레드를 멈춘다. 100MB+ 로그에서 수 초 단위 freeze
        를 유발하므로 모든 파싱을 백그라운드 스레드로 밀어내고 결과만
        `root.after(0, ...)` 로 메인 스레드에 돌려 UI 를 갱신한다.
        """
        if self._stats_summary is None:
            return
        # 사용자에게 작업이 진행 중임을 즉시 알림
        try:
            self._stats_summary.config(text="비용 로그 분석 중…")
        except tk.TclError:
            return
        threading.Thread(target=self._compute_cost_bg, daemon=True).start()

    def _compute_cost_bg(self) -> None:
        try:
            from pipeline.cost_estimator import (
                UsageStats,
                aggregate,
                estimate_cost,
                estimate_per_call,
                parse_log_file,
            )
            from pipeline.vod_log_index import index_vods_from_log

            calls = parse_log_file(self.log_path)
            stats = aggregate(calls)
            entries = index_vods_from_log(self.log_path)
            # UsageStats per VOD 미리 계산 (estimate_cost 는 순수 함수)
            vod_rows = []
            for e in reversed(entries):
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
                vod_rows.append((
                    e.video_no,
                    e.title,
                    len(e.calls),
                    e.total_input,
                    e.total_output,
                    e.actual_cost_usd,
                    estimate_cost(e_stats, "haiku"),
                    estimate_cost(e_stats, "sonnet"),
                    estimate_cost(e_stats, "opus"),
                ))
            per_model = {
                m: (estimate_per_call(stats, m), estimate_cost(stats, m))
                for m in ("haiku", "sonnet", "opus")
            }
        except Exception as e:  # noqa: BLE001
            if self.root is not None:
                self.root.after(0, lambda: self._stats_summary
                                and self._stats_summary.config(text=f"비용 분석 실패: {e}"))
            return
        if self.root is None:
            return
        self.root.after(
            0,
            lambda: self._apply_cost_results(stats, per_model, vod_rows[:50]),
        )

    def _apply_cost_results(self, stats, per_model, vod_rows) -> None:
        from pipeline.cost_estimator import (
            format_tokens, format_usd, PRICING,
        )

        if self._stats_summary is None:
            return
        if stats.calls == 0:
            self._stats_summary.config(
                text="기록된 Claude API 호출이 없습니다. VOD 를 최소 1개 처리한 뒤 [다시 계산]."
            )
            if self._cost_tree is not None:
                self._cost_tree.delete(*self._cost_tree.get_children())
            if self._breakdown_tree is not None:
                self._breakdown_tree.delete(*self._breakdown_tree.get_children())
            self._render_trend_chart()
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

        if self._cost_tree is not None:
            self._cost_tree.delete(*self._cost_tree.get_children())
            actual = stats.actual_cost_usd
            for model in ("haiku", "sonnet", "opus"):
                per, total = per_model[model]
                vs = f"{total / actual:.2f}×" if actual > 0 else "-"
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

        if self._breakdown_tree is not None:
            self._breakdown_tree.delete(*self._breakdown_tree.get_children())
            for row in vod_rows:
                (vno, title, ncalls, tin, tout, actual, haiku, sonnet, opus) = row
                self._breakdown_tree.insert(
                    "",
                    "end",
                    values=(
                        vno,
                        title[:60],
                        ncalls,
                        f"{format_tokens(tin)} / {format_tokens(tout)}",
                        format_usd(actual),
                        f"{format_usd(haiku)} / {format_usd(sonnet)} / {format_usd(opus)}",
                    ),
                )

        # 트렌드 차트 렌더 (자체적으로 aggregate_by_day 를 돌지만 14일만 스캔하므로
        # 현재로서는 작은 비용; 필요시 동일 패턴으로 bg 이관).
        self._render_trend_chart()

    def _render_trend_chart(self) -> None:
        """최근 14일 실측 비용을 Canvas 막대그래프로 렌더."""
        if self._trend_canvas is None:
            return
        canvas = self._trend_canvas
        canvas.delete("all")

        try:
            from pipeline.cost_estimator import format_usd
            from pipeline.cost_trend import aggregate_by_day
        except Exception:  # noqa: BLE001
            return

        series = aggregate_by_day(self.log_path, days=14)
        if not series:
            return

        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 120)
        pad_left, pad_right = 40, 16
        pad_top, pad_bottom = 12, 26
        plot_w = max(width - pad_left - pad_right, 100)
        plot_h = max(height - pad_top - pad_bottom, 40)

        max_cost = max((d.actual_cost_usd for d in series), default=0.0)
        total_cost = sum(d.actual_cost_usd for d in series)
        total_calls = sum(d.calls for d in series)

        # 배경 + 축선
        canvas.create_line(
            pad_left,
            pad_top + plot_h,
            pad_left + plot_w,
            pad_top + plot_h,
            fill="#3b4261",
        )
        # y축 상한 레이블
        if max_cost > 0:
            canvas.create_text(
                pad_left - 6,
                pad_top,
                text=format_usd(max_cost),
                fill="#7a86a8",
                anchor="e",
                font=("Segoe UI", 8),
            )
            canvas.create_text(
                pad_left - 6,
                pad_top + plot_h,
                text="$0",
                fill="#7a86a8",
                anchor="e",
                font=("Segoe UI", 8),
            )

        n = len(series)
        slot = plot_w / n
        bar_w = max(slot * 0.62, 4)

        for i, d in enumerate(series):
            cx = pad_left + slot * (i + 0.5)
            if max_cost > 0 and d.actual_cost_usd > 0:
                h = (d.actual_cost_usd / max_cost) * plot_h
            else:
                h = 0
            x0 = cx - bar_w / 2
            x1 = cx + bar_w / 2
            y0 = pad_top + plot_h - h
            y1 = pad_top + plot_h
            color = "#7aa2f7" if d.actual_cost_usd > 0 else "#2a2e42"
            if h > 0:
                canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            # 날짜 라벨: 매 2일마다 혹은 마지막 날
            if i % 2 == 0 or i == n - 1:
                canvas.create_text(
                    cx,
                    pad_top + plot_h + 12,
                    text=d.day.strftime("%m-%d"),
                    fill="#7a86a8",
                    font=("Segoe UI", 8),
                )

        if self._trend_summary is not None:
            if total_calls == 0:
                txt = "최근 14일간 기록된 호출이 없습니다."
            else:
                avg = total_cost / 14
                txt = (
                    f"합계 {format_usd(total_cost)} · 호출 {total_calls}회 · "
                    f"일평균 {format_usd(avg)} · 최고일 {format_usd(max_cost)}"
                )
            self._trend_summary.config(text=txt)

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

        # ---- 파이프라인 제어 (트레이 아이콘이 안 떠도 여기서 제어) ----
        ctrl_group = ttk.LabelFrame(
            frame, text="파이프라인 제어", padding=12
        )
        ctrl_group.pack(fill="x", pady=(24, 8))
        ttk.Label(
            ctrl_group,
            text=(
                "파이프라인은 이 창 안에서 백그라운드 스레드로 돌고 있습니다. "
                "창을 닫으면 파이프라인도 종료됩니다."
            ),
            foreground="#8a8a8a",
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        ctrl_row = ttk.Frame(ctrl_group)
        ctrl_row.pack(anchor="w")
        ttk.Button(
            ctrl_row,
            text="일시정지",
            command=self._ctrl_pause,
            width=14,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            ctrl_row,
            text="재개",
            command=self._ctrl_resume,
            width=14,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            ctrl_row,
            text="파이프라인 종료",
            command=self._ctrl_quit,
            width=14,
        ).pack(side="left", padx=(0, 8))

        self._ctrl_status = ttk.Label(
            ctrl_group, text="", foreground="#7a86a8"
        )
        self._ctrl_status.pack(anchor="w", pady=(10, 0))

    def _ctrl_pause(self) -> None:
        try:
            self.daemon.pause()
            self._set_ctrl_status("✓ 일시정지되었습니다.")
        except Exception as e:  # noqa: BLE001
            self._set_ctrl_status(f"일시정지 실패: {e}")

    def _ctrl_resume(self) -> None:
        try:
            self.daemon.resume()
            self._set_ctrl_status("✓ 재개되었습니다.")
        except Exception as e:  # noqa: BLE001
            self._set_ctrl_status(f"재개 실패: {e}")

    def _ctrl_quit(self) -> None:
        """파이프라인 + 창을 함께 종료. 창 닫기와 동일한 경로 사용."""
        self._set_ctrl_status("종료 중… 진행 중인 VOD 를 마무리합니다 (최대 5초).")
        if self.root is not None:
            # 상태 라벨이 그려질 기회를 준 뒤 실제 종료
            self.root.after(100, self._on_close)

    def _set_ctrl_status(self, text: str) -> None:
        if hasattr(self, "_ctrl_status") and self._ctrl_status is not None:
            self._ctrl_status.config(text=text)

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
        """상태 파일 읽기.

        daemon 이 `os.replace()` 직전의 tmp 쓰기 단계에 있으면 드물게 JSON 이
        부분적으로 보일 수 있다. 과거에는 이런 순간에 빈 dict 를 돌려 대시보드
        UI 가 "처리 이력 없음" 으로 깜빡였다. 짧게 재시도한다.
        """
        if not self.state_path.exists():
            return {}
        for _ in range(5):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                import time
                time.sleep(0.02)
                continue
            except OSError:
                return {}
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
        # B36: VOD 컬럼 = "<video_no> <title 30자>" / 비고 = "<MM-DD HH:MM> · <info>"
        self.status_tree.delete(*self.status_tree.get_children())
        for key, v in active:
            status = v.get("status", "?")
            label = _STATUS_LABELS.get(status, status)
            updated = _short_ts(v.get("updated_at", ""))

            # VOD 컬럼: video_no + 제목 (30자 잘림). 제목 미상이면 fallback.
            video_no = v.get("video_no") or (
                key.split(":", 1)[-1] if ":" in key else key
            )
            title = (v.get("title") or "").strip()
            if title:
                display_title = title if len(title) <= 30 else title[:30] + "…"
                vod_display = f"{video_no} {display_title}"
            else:
                vod_display = video_no

            # 비고 컬럼: publish_date + 기존 info (error / progress)
            publish_short = _format_publish_date(v.get("publish_date", ""))
            info_raw = v.get("error") or v.get("progress") or ""
            info_parts = [p for p in (publish_short, info_raw) if p]
            info = " · ".join(info_parts) if info_parts else (v.get("video_no") or "")

            row = self.status_tree.insert(
                "",
                "end",
                values=(vod_display, label, updated, info),
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
        # 스킵: terminal status (completed / skipped_*) 가 아닌 모든 엔트리에 노출.
        # 진행 중이면 협력적 cancel, 비-진행이면 즉시 skipped_user 마킹.
        if status not in ("completed", "skipped_bootstrap", "skipped_user"):
            menu.add_command(
                label="스킵 (영구 제외 + work dir 정리)",
                command=lambda: self._action_skip(key, status),
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

    def _open_manual_process_dialog(self) -> None:
        """VOD 번호 + (옵션) 스트리머/키워드/limit 를 입력받아 수동 처리.

        spawn 명령:
            python -m pipeline.main --process <VOD>
                [--streamer-name "..."] [--search-keyword K1 --search-keyword K2 ...]
                [--limit-duration N]
        """
        if self.root is None:
            return
        from tkinter import messagebox

        win = tk.Toplevel(self.root)
        win.title("수동 VOD 처리")
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()

        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)

        # VOD 번호 (필수)
        ttk.Label(frm, text="VOD 번호 (필수)").grid(row=0, column=0, sticky="w", pady=4)
        vod_var = tk.StringVar()
        vod_entry = ttk.Entry(frm, textvariable=vod_var, width=24)
        vod_entry.grid(row=0, column=1, sticky="we", padx=(8, 0), pady=4)

        # 스트리머 이름 (선택)
        ttk.Label(frm, text="스트리머 이름 (선택)").grid(row=1, column=0, sticky="w", pady=4)
        streamer_var = tk.StringVar()
        ttk.Entry(frm, textvariable=streamer_var, width=24).grid(
            row=1, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # 검색 키워드 (선택, 콤마 구분)
        ttk.Label(
            frm, text="fmkorea 검색 키워드\n(콤마 구분, 선택)"
        ).grid(row=2, column=0, sticky="w", pady=4)
        keyword_var = tk.StringVar()
        ttk.Entry(frm, textvariable=keyword_var, width=24).grid(
            row=2, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # fmkorea max-pages override (선택)
        ttk.Label(
            frm, text="fmkorea 페이지 수\n(키워드당, 빈값 = 설정 기본값)"
        ).grid(row=3, column=0, sticky="w", pady=4)
        max_pages_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=max_pages_var, width=24).grid(
            row=3, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # 테스트 모드 — limit-duration (초 단위, 선택)
        ttk.Label(
            frm, text="테스트 모드 — 앞 N초만\n(0 또는 빈값 = 전체)"
        ).grid(row=4, column=0, sticky="w", pady=4)
        limit_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=limit_var, width=24).grid(
            row=4, column=1, sticky="we", padx=(8, 0), pady=4
        )

        # 안내 라벨
        ttk.Label(
            frm,
            text=(
                "기존 데몬과 별도 프로세스로 detached 실행됩니다.\n"
                "RESUME 캐시 (다운로드/SRT/채팅) 가 있으면 자동 활용."
            ),
            foreground="#7a86a8",
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 6))

        # 버튼
        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=2, sticky="we", pady=(8, 0))
        btns.columnconfigure(0, weight=1)

        def _submit():
            video_no = vod_var.get().strip()
            if not video_no.isdigit():
                messagebox.showerror(
                    "입력 오류", "VOD 번호는 숫자여야 합니다.", parent=win
                )
                return
            streamer_name = streamer_var.get().strip() or None
            keywords_raw = keyword_var.get().strip()
            keywords = [
                k.strip() for k in keywords_raw.split(",") if k.strip()
            ] if keywords_raw else []
            max_pages_raw = max_pages_var.get().strip()
            max_pages: int = 0
            if max_pages_raw:
                if not max_pages_raw.isdigit() or int(max_pages_raw) <= 0:
                    messagebox.showerror(
                        "입력 오류", "fmkorea 페이지 수는 1 이상의 정수여야 합니다.",
                        parent=win,
                    )
                    return
                max_pages = int(max_pages_raw)
            limit_raw = limit_var.get().strip()
            limit_sec: int = 0
            if limit_raw:
                if not limit_raw.isdigit():
                    messagebox.showerror(
                        "입력 오류", "테스트 모드 N초는 정수여야 합니다.",
                        parent=win,
                    )
                    return
                limit_sec = int(limit_raw)
            win.destroy()
            self._action_manual_process(
                video_no, streamer_name=streamer_name,
                keywords=keywords, max_pages=max_pages,
                limit_duration_sec=limit_sec,
            )

        ttk.Button(btns, text="처리 시작", command=_submit, width=12).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(btns, text="취소", command=win.destroy, width=10).pack(
            side="right"
        )

        frm.columnconfigure(1, weight=1)
        vod_entry.focus_set()
        # Enter 키로 submit
        win.bind("<Return>", lambda _e: _submit())
        win.bind("<Escape>", lambda _e: win.destroy())

    def _build_manual_process_cmd(
        self,
        video_no: str,
        streamer_name: Optional[str] = None,
        keywords: Optional[list] = None,
        max_pages: int = 0,
        limit_duration_sec: int = 0,
    ) -> list:
        """spawn 할 argv 리스트를 빌드 (단위 테스트 가능하도록 분리).

        형식: [python, -m, pipeline.main, --process, VOD, ...옵션]
        """
        import sys as _sys
        cmd = [_sys.executable, "-m", "pipeline.main", "--process", video_no]
        if streamer_name:
            cmd += ["--streamer-name", streamer_name]
        if keywords:
            for k in keywords:
                cmd += ["--search-keyword", k]
        if max_pages and max_pages > 0:
            cmd += ["--max-pages", str(max_pages)]
        if limit_duration_sec and limit_duration_sec > 0:
            cmd += ["--limit-duration", str(limit_duration_sec)]
        return cmd

    def _action_manual_process(
        self,
        video_no: str,
        streamer_name: Optional[str] = None,
        keywords: Optional[list] = None,
        max_pages: int = 0,
        limit_duration_sec: int = 0,
    ) -> None:
        """수동 처리 spawn — _action_reprocess 와 동일 패턴 (detached, env 보존)."""
        import subprocess
        import sys as _sys

        cmd = self._build_manual_process_cmd(
            video_no, streamer_name=streamer_name,
            keywords=keywords, max_pages=max_pages,
            limit_duration_sec=limit_duration_sec,
        )
        try:
            creationflags = 0
            if _sys.platform == "win32":
                creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                creationflags=creationflags,
                close_fds=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            label_parts = [f"수동 처리: {video_no}"]
            if streamer_name:
                label_parts.append(f"스트리머={streamer_name}")
            if keywords:
                label_parts.append(f"키워드={','.join(keywords)}")
            if max_pages:
                label_parts.append(f"페이지={max_pages}")
            if limit_duration_sec:
                label_parts.append(f"앞 {limit_duration_sec}초만")
            self._header_flash(" / ".join(label_parts))
            threading.Thread(target=self._refresh_status_bg, daemon=True).start()
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"수동 처리 실패: {e}")

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
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self._header_flash(f"재처리 요청: {video_no}")
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"재처리 실패: {e}")

    _ACTIVE_STATUSES = {
        "processing", "collecting", "analyzing", "transcribing",
        "chunking", "summarizing", "saving",
    }

    def _action_skip(self, key: str, status: str) -> None:
        """VOD 스킵.

        진행 중 (collecting / transcribing / ...): state 에 skip_requested 플래그 만
            설정. process_vod 가 다음 stage 경계 또는 Whisper batch 경계에서
            SkipRequested 를 raise → 외부 핸들러가 skipped_user 마킹 + work_dir 정리.
            대시보드는 "스킵 요청됨" 안내만 띄우고 즉시 반환.

        비-진행 (대기/error/pending_retry): 즉시 skipped_user 마킹 + work_dir 정리.
            진행 중인 worker 가 없으므로 협력적 cancel 불필요.
        """
        from tkinter import messagebox
        import shutil as _shutil

        if self.root is None:
            return
        # 키 → (channel_id, video_no) 분리
        if ":" in key:
            channel_id, video_no = key.split(":", 1)
        else:
            channel_id, video_no = None, key

        is_active = status in self._ACTIVE_STATUSES
        if is_active:
            confirm_msg = (
                f"VOD [{video_no}] 가 현재 '{status}' 진행 중입니다.\n\n"
                "스킵을 요청하면 다음 stage 경계 또는 Whisper batch 경계에서\n"
                "처리를 중단하고 work_dir 을 정리합니다.\n\n"
                "Whisper 진행 중이면 현재 batch 가 끝나야 멈추므로\n"
                "최대 수 분이 걸릴 수 있습니다. 계속할까요?"
            )
        else:
            confirm_msg = (
                f"VOD [{video_no}] 를 영구 스킵 처리합니다.\n"
                "monitor 가 다음 폴링부터 이 VOD 를 다시 잡지 않습니다.\n"
                "work_dir 도 정리됩니다. 계속할까요?"
            )
        if not messagebox.askyesno("스킵 확인", confirm_msg, parent=self.root):
            return

        # work_dir 경로 — pipeline_config.json 의 work_dir 기준
        work_dir = None
        try:
            cfg_work = (self.cfg or {}).get("work_dir", "./work")
            work_dir = os.path.join(cfg_work, video_no)
        except Exception:  # noqa: BLE001
            pass

        if is_active:
            # 협력적 cancel — 플래그만 설정. work_dir 정리는 process_vod 가 담당.
            try:
                ok = self.state.request_skip(video_no, channel_id=channel_id)
            except Exception as e:  # noqa: BLE001
                self._header_flash(f"스킵 요청 실패: {e}")
                return
            if ok:
                self._header_flash(
                    f"스킵 요청됨: {video_no} (다음 stage 경계에서 적용)"
                )
            else:
                self._header_flash(f"엔트리 없음: {video_no}")
        else:
            # 즉시 skipped_user 마킹 + work_dir 정리
            try:
                self.state.mark_skipped_user(
                    video_no, channel_id=channel_id, reason="user skip via dashboard"
                )
            except Exception as e:  # noqa: BLE001
                self._header_flash(f"스킵 마킹 실패: {e}")
                return
            if work_dir and os.path.isdir(work_dir):
                try:
                    _shutil.rmtree(work_dir, ignore_errors=True)
                except Exception as e:  # noqa: BLE001
                    self._header_flash(
                        f"스킵 OK ({video_no}) — work_dir 정리 실패: {e}"
                    )
                    return
            self._header_flash(f"스킵 완료: {video_no} (영구 제외)")

        threading.Thread(target=self._refresh_status_bg, daemon=True).start()

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
        """단일 엔트리 제거 — PipelineState 의 _lock 을 사용하여 daemon 과 race 방지.

        이전에는 대시보드가 pipeline_state.json 을 직접 rename-write 했는데,
        daemon 스레드의 `state.update()` 와 TOCTOU 경쟁이 발생할 수 있었다.
        이제는 `PipelineState.remove_entry()` 에 위임한다.
        """
        try:
            removed = self.state.remove_entry(key)
            if removed:
                self._header_flash(f"상태 제거: {key}")
                threading.Thread(target=self._refresh_status_bg, daemon=True).start()
            else:
                self._header_flash(f"엔트리 없음: {key}")
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"제거 실패: {e}")

    def _clear_all_errors(self) -> None:
        """status == 'error' 또는 'pending_retry' 엔트리를 한꺼번에 제거."""
        from tkinter import messagebox

        if self.root is None:
            return
        # 현재 카운트를 미리 계산하여 사용자에게 표시
        try:
            data = self._read_state()
            err_count = sum(
                1 for v in data.get("processed_vods", {}).values()
                if v.get("status") in ("error", "pending_retry")
            )
        except Exception:  # noqa: BLE001
            err_count = 0
        if err_count == 0:
            messagebox.showinfo("오류 기록 제거", "제거할 오류 기록이 없습니다.")
            return
        ok = messagebox.askyesno(
            "오류 기록 일괄 제거",
            f"{err_count}개의 오류/재시도 대기 엔트리를 제거합니다.\n"
            "(제거된 VOD 는 이후 재시도 대상에서도 빠집니다.)\n\n계속하시겠습니까?",
        )
        if not ok:
            return
        try:
            removed = self.state.clear_errors(include_pending_retry=True)
            self._header_flash(f"오류 기록 {removed}개 제거됨")
            threading.Thread(target=self._refresh_status_bg, daemon=True).start()
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"일괄 제거 실패: {e}")

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

    def _on_report_rightclick(self, event) -> None:
        """완료된 리포트 우클릭 → 재처리(모델 선택) / 리포트 열기 / 경로 복사."""
        if self.report_tree is None or self.root is None:
            return
        row = self.report_tree.identify_row(event.y)
        if not row:
            return
        self.report_tree.selection_set(row)
        values = self.report_tree.item(row, "values")
        if len(values) < 3:
            return
        title, _updated, path = values[0], values[1], values[2]

        # HTML stem → video_no 복원: processed_vods 에서 output_html 역매칭.
        video_no = self._video_no_for_report_path(path)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="리포트 열기", command=lambda: self._open_path(path))
        menu.add_separator()
        if video_no:
            sub = tk.Menu(menu, tearoff=0)
            for label, model_key in (
                ("Haiku (경량·저가)", "haiku"),
                ("Sonnet (기본)", "sonnet"),
                ("Opus (최고 품질)", "opus"),
                ("현재 설정 모델", ""),
            ):
                sub.add_command(
                    label=label,
                    command=lambda vn=video_no, mk=model_key: self._reprocess_with_model(vn, mk),
                )
            menu.add_cascade(label="다른 모델로 재요약", menu=sub)
        else:
            menu.add_command(
                label="(재처리 불가 — VOD 매칭 실패)", state="disabled"
            )
        menu.add_separator()
        menu.add_command(
            label="경로 복사", command=lambda: _copy_to_clipboard(self.root, path)
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _video_no_for_report_path(self, html_path: str) -> Optional[str]:
        """output_html 경로로부터 processed_vods 의 video_no 찾기."""
        state = self._read_state()
        processed = state.get("processed_vods", {}) or {}
        # 경로 정규화
        target = str(Path(html_path).resolve()).lower()
        for key, v in processed.items():
            cand = v.get("output_html")
            if not cand:
                continue
            try:
                if str(Path(cand).resolve()).lower() == target:
                    return v.get("video_no") or key.split(":", 1)[-1]
            except OSError:
                continue
        return None

    def _reprocess_with_model(self, video_no: str, model: str) -> None:
        """`python -m pipeline.main --process <vn> --claude-model <m>` 를 백그라운드 실행.

        SRT / chat JSON sidecar 가 work_dir 에 남아있으므로 Whisper/채팅API 는 스킵되고
        요약만 새 모델로 다시 돌아간다. (cleanup_work_dir_on_success 에서 보존 처리됨)
        """
        import subprocess
        import sys as _sys

        args = [_sys.executable, "-m", "pipeline.main", "--process", video_no]
        if model:
            args += ["--claude-model", model]
        try:
            creationflags = 0
            if _sys.platform == "win32":
                creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            subprocess.Popen(
                args,
                cwd=str(self.project_root),
                creationflags=creationflags,
                close_fds=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self._header_flash(
                f"재요약 요청: {video_no} (model={model or '기본'})"
            )
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"재요약 실패: {e}")

    def _open_path(self, path: str) -> None:
        try:
            webbrowser.open(Path(path).resolve().as_uri())
        except Exception:  # noqa: BLE001
            pass

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
                # 데몬에 즉시 통지 — 다음 폴링부터 새 채널/쿠키/폴링간격이 적용된다.
                # 이전엔 이 호출이 없어 앱 재시작 전까지 설정 변경이 무시됐다.
                try:
                    if getattr(self, "daemon", None) is not None:
                        self.daemon.update_config(new_cfg)
                except Exception:  # noqa: BLE001
                    # 통지 실패가 저장 자체를 되돌리진 않음 (다음 재시작에 반영)
                    pass

            # 대시보드 root 를 parent 로 넘겨 Toplevel 하나만 뜨도록 한다.
            # (이전엔 두 번째 Tk + withdraw→deiconify 로 창이 두 개 보였다)
            # 중복 열림 방지: 이미 살아있는 settings 창이 있으면 포커스만 이동.
            if getattr(self, "_settings_win", None) is not None:
                try:
                    if self._settings_win.root.winfo_exists():
                        self._settings_win.root.lift()
                        self._settings_win.root.focus_force()
                        return
                except tk.TclError:
                    pass
            self._settings_win = open_settings(on_save=_on_save, parent=self.root)
            try:
                self._settings_win.root.protocol(
                    "WM_DELETE_WINDOW",
                    lambda: self._close_settings(),
                )
            except (tk.TclError, AttributeError):
                pass
        except Exception as e:  # noqa: BLE001
            self._header_flash(f"설정 창 실패: {e}")

    def _close_settings(self) -> None:
        win = getattr(self, "_settings_win", None)
        if win is not None:
            try:
                win.root.destroy()
            except tk.TclError:
                pass
        self._settings_win = None

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


def _format_publish_date(value: str) -> str:
    """B36: VOD publish_date 를 비고 컬럼용 짧은 포맷으로.

    입력 가능 포맷:
      - ISO: "2026-04-26T17:05:10+09:00"
      - 공백 구분: "2026-04-26 17:05:10"
      - 일부만 있음: "2026-04-26"
      - 빈 문자열 / None → ""
    출력: "04-26 17:05" 또는 "04-26" (시각 없을 때).
    """
    if not value:
        return ""
    s = str(value).strip().replace("T", " ").replace("Z", "+00:00")
    try:
        import datetime

        has_time = ":" in s
        # ISO 형식 우선 시도 (공백을 T로 복원)
        try:
            dt = datetime.datetime.fromisoformat(s.replace(" ", "T", 1))
            return dt.strftime("%m-%d %H:%M") if has_time else dt.strftime("%m-%d")
        except ValueError:
            pass
        # 날짜만 있는 케이스 (다른 구분자 fallback)
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                dt = datetime.datetime.strptime(s[:10], fmt)
                return dt.strftime("%m-%d")
            except ValueError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return s[:16]


def open_dashboard(cfg: Optional[dict] = None) -> None:
    """외부 호출 진입점 (트레이에서 사용)."""
    Dashboard.open(cfg=cfg)


def _dashboard_lock_path(cfg: dict) -> Path:
    out_dir = Path(cfg.get("output_dir", "./output"))
    return out_dir / "pipeline.dashboard.lock"


def _acquire_dashboard_lock(lock_path: Path) -> bool:
    """프로세스-레벨 싱글톤. 다른 대시보드 프로세스가 살아 있으면 False."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            pid = 0
        if pid and _is_pid_alive(pid) and pid != os.getpid():
            return False
    try:
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        return False
    return True


def _release_dashboard_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        pass


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                code = ctypes.c_ulong(0)
                if k32.GetExitCodeProcess(h, ctypes.byref(code)) == 0:
                    return False  # 쿼리 실패 → 죽은 것으로 간주
                return code.value == STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        except Exception:  # noqa: BLE001
            return True  # 의심스러우면 살아있다고 가정 (중복 기동 회피)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def main() -> int:
    from pipeline._io_encoding import force_utf8_stdio
    from pipeline.config import load_config

    force_utf8_stdio()
    cfg = load_config()

    # OS-레벨 싱글톤 — 두 개의 pythonw -m pipeline.dashboard 가 동시에 떠
    # UI 가 2개 보이는 사고 방지.
    lock = _dashboard_lock_path(cfg)
    if not _acquire_dashboard_lock(lock):
        # 이미 실행 중 → 조용히 종료 (기존 창을 사용자가 보게 둔다)
        return 0
    try:
        open_dashboard(cfg)
    finally:
        _release_dashboard_lock(lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
