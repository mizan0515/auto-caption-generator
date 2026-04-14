"""파이프라인 설정 GUI (tkinter)

트레이 앱 또는 독립 실행으로 pipeline_config.json을 편집.
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from .config import load_config, save_config, _config_path


# ── 필드 정의: (config key, 라벨, 타입, 설명) ──
FIELDS = [
    # 기본 설정
    ("streamer_name",        "스트리머 이름",       "str",   "모니터링할 스트리머 이름 (표시용)"),
    ("target_channel_id",    "채널 ID",            "str",   "Chzzk 채널 ID (32자리 hex)"),
    ("poll_interval_sec",    "폴링 간격 (초)",      "int",   "새 VOD 확인 주기 (기본: 300초 = 5분)"),
    ("download_resolution",  "다운로드 해상도",     "int",   "VOD 다운로드 해상도 (기본: 144)"),

    # 커뮤니티
    ("fmkorea_enabled",      "fmkorea 수집",       "bool",  "fmkorea 커뮤니티 스크레이핑 활성화"),
    ("fmkorea_search_keywords", "검색 키워드",     "list",  "쉼표로 구분 (예: 탬탬버린,탬탬)"),
    ("fmkorea_max_pages",    "최대 페이지",         "int",   "키워드당 검색 페이지 수"),
    ("fmkorea_max_posts",    "최대 게시글",         "int",   "수집할 최대 게시글 수"),

    # 자막/요약
    ("chunk_max_chars",      "청크 최대 글자",      "int",   "SRT 청크 분할 기준 (기본: 150000)"),
    ("chunk_overlap_sec",    "청크 오버랩 (초)",    "int",   "청크 간 겹침 구간 (기본: 45)"),
    ("claude_timeout_sec",   "Claude 타임아웃 (초)","int",   "Claude CLI 호출 제한시간"),

    # 경로
    ("output_dir",           "출력 디렉터리",       "str",   "리포트 저장 경로"),
    ("work_dir",             "작업 디렉터리",       "str",   "임시 파일 저장 경로"),
    ("auto_cleanup",         "자동 정리",           "bool",  "처리 완료 후 임시 파일 삭제"),
]

COOKIE_FIELDS = [
    ("NID_AUT", "NID_AUT", "Chzzk 인증 쿠키"),
    ("NID_SES", "NID_SES", "Chzzk 세션 쿠키"),
]


class SettingsWindow:
    def __init__(self, parent=None, on_save=None):
        """
        Args:
            parent: 부모 tk 윈도우 (없으면 새 Tk 생성)
            on_save: 저장 완료 후 콜백 (cfg dict 전달)
        """
        self.on_save = on_save
        self.cfg = load_config()
        self.widgets = {}

        if parent:
            self.root = tk.Toplevel(parent)
        else:
            self.root = tk.Tk()

        self.root.title("파이프라인 설정")
        self.root.geometry("600x720")
        self.root.resizable(False, True)

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        # 스크롤 가능한 캔버스
        canvas = tk.Canvas(self.root)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        self.frame = ttk.Frame(canvas)

        self.frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 마우스 휠 스크롤
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        row = 0

        # ── 기본 설정 ──
        row = self._add_section("기본 설정", row)
        for key, label, ftype, desc in FIELDS[:4]:
            row = self._add_field(key, label, ftype, desc, row)

        # ── 커뮤니티 설정 ──
        row = self._add_section("커뮤니티 수집", row)
        for key, label, ftype, desc in FIELDS[4:8]:
            row = self._add_field(key, label, ftype, desc, row)

        # ── 자막/요약 설정 ──
        row = self._add_section("자막 / 요약", row)
        for key, label, ftype, desc in FIELDS[8:11]:
            row = self._add_field(key, label, ftype, desc, row)

        # ── 경로 설정 ──
        row = self._add_section("경로 / 정리", row)
        for key, label, ftype, desc in FIELDS[11:]:
            row = self._add_field(key, label, ftype, desc, row)

        # ── 쿠키 설정 ──
        row = self._add_section("Chzzk 쿠키", row)
        ttk.Label(
            self.frame,
            text="F12 > Application > Cookies > chzzk.naver.com 에서 복사",
            foreground="gray",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 4))
        row += 1

        for key, label, desc in COOKIE_FIELDS:
            cookie_key = f"cookie_{key}"
            ttk.Label(self.frame, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=2)
            entry = ttk.Entry(self.frame, width=50, show="*")
            entry.grid(row=row, column=1, sticky="ew", padx=12, pady=2)
            self.widgets[cookie_key] = entry
            row += 1

        # 쿠키 표시/숨기기 토글
        self._cookie_visible = False
        toggle_btn = ttk.Button(self.frame, text="쿠키 표시", command=self._toggle_cookie_visibility)
        toggle_btn.grid(row=row, column=1, sticky="e", padx=12, pady=4)
        self._cookie_toggle_btn = toggle_btn
        row += 1

        # ── 버튼 ──
        row += 1
        btn_frame = ttk.Frame(self.frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=16)

        ttk.Button(btn_frame, text="저장", command=self._save, width=12).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="취소", command=self.root.destroy, width=12).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="초기화", command=self._reset, width=12).pack(side="left", padx=8)

        # 설정 파일 경로 표시
        row += 1
        ttk.Label(
            self.frame,
            text=f"설정 파일: {_config_path()}",
            foreground="gray",
            font=("", 8),
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

        # 컬럼 가중치
        self.frame.columnconfigure(1, weight=1)

    def _add_section(self, title: str, row: int) -> int:
        sep = ttk.Separator(self.frame, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(12, 4))
        row += 1
        lbl = ttk.Label(self.frame, text=title, font=("", 11, "bold"))
        lbl.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 4))
        return row + 1

    def _add_field(self, key: str, label: str, ftype: str, desc: str, row: int) -> int:
        ttk.Label(self.frame, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=2)

        if ftype == "bool":
            var = tk.BooleanVar()
            widget = ttk.Checkbutton(self.frame, variable=var)
            widget.grid(row=row, column=1, sticky="w", padx=12, pady=2)
            self.widgets[key] = var
        elif ftype == "list":
            entry = ttk.Entry(self.frame, width=50)
            entry.grid(row=row, column=1, sticky="ew", padx=12, pady=2)
            self.widgets[key] = entry
        elif ftype == "int":
            entry = ttk.Entry(self.frame, width=20)
            entry.grid(row=row, column=1, sticky="w", padx=12, pady=2)
            self.widgets[key] = entry
        else:  # str
            entry = ttk.Entry(self.frame, width=50)
            entry.grid(row=row, column=1, sticky="ew", padx=12, pady=2)
            self.widgets[key] = entry

        row += 1
        # 설명 라벨
        ttk.Label(self.frame, text=desc, foreground="gray", font=("", 8)).grid(
            row=row, column=1, sticky="w", padx=14, pady=(0, 2)
        )
        return row + 1

    def _toggle_cookie_visibility(self):
        self._cookie_visible = not self._cookie_visible
        show = "" if self._cookie_visible else "*"
        for key, _, _ in COOKIE_FIELDS:
            self.widgets[f"cookie_{key}"].configure(show=show)
        self._cookie_toggle_btn.configure(
            text="쿠키 숨기기" if self._cookie_visible else "쿠키 표시"
        )

    def _load_values(self):
        """설정값을 위젯에 로드"""
        for key, _, ftype, _ in FIELDS:
            val = self.cfg.get(key, "")
            widget = self.widgets[key]

            if ftype == "bool":
                widget.set(bool(val))
            elif ftype == "list":
                widget.delete(0, tk.END)
                if isinstance(val, list):
                    widget.insert(0, ", ".join(val))
                else:
                    widget.insert(0, str(val))
            elif ftype == "int":
                widget.delete(0, tk.END)
                widget.insert(0, str(val))
            else:
                widget.delete(0, tk.END)
                widget.insert(0, str(val))

        # 쿠키
        cookies = self.cfg.get("cookies", {})
        for key, _, _ in COOKIE_FIELDS:
            w = self.widgets[f"cookie_{key}"]
            w.delete(0, tk.END)
            w.insert(0, cookies.get(key, ""))

    def _collect_values(self) -> dict:
        """위젯에서 설정값 수집"""
        cfg = dict(self.cfg)

        for key, label, ftype, _ in FIELDS:
            widget = self.widgets[key]

            if ftype == "bool":
                cfg[key] = widget.get()
            elif ftype == "list":
                raw = widget.get().strip()
                cfg[key] = [s.strip() for s in raw.split(",") if s.strip()]
            elif ftype == "int":
                raw = widget.get().strip()
                try:
                    cfg[key] = int(raw)
                except ValueError:
                    messagebox.showerror("입력 오류", f"'{label}'은(는) 숫자여야 합니다: {raw}")
                    return None
            else:
                cfg[key] = widget.get().strip()

        # 쿠키
        cfg["cookies"] = {}
        for key, _, _ in COOKIE_FIELDS:
            cfg["cookies"][key] = self.widgets[f"cookie_{key}"].get().strip()

        return cfg

    def _save(self):
        cfg = self._collect_values()
        if cfg is None:
            return

        # 채널 ID 검증
        cid = cfg.get("target_channel_id", "")
        if len(cid) != 32:
            messagebox.showwarning("경고", f"채널 ID가 32자가 아닙니다 ({len(cid)}자). 확인해주세요.")

        save_config(cfg)
        self.cfg = cfg

        if self.on_save:
            self.on_save(cfg)

        messagebox.showinfo("저장 완료", f"설정이 저장되었습니다.\n{_config_path()}")
        self.root.destroy()

    def _reset(self):
        if messagebox.askyesno("초기화", "설정을 기본값으로 초기화하시겠습니까?"):
            from .config import DEFAULT_CONFIG
            self.cfg = dict(DEFAULT_CONFIG)
            self._load_values()

    def show(self):
        """창 표시 (독립 실행 시)"""
        self.root.mainloop()


def open_settings(on_save=None):
    """설정 창을 새 스레드에서 열기 (트레이 앱에서 호출용)"""
    import threading

    def _run():
        root = tk.Tk()
        root.withdraw()
        win = SettingsWindow(parent=root, on_save=on_save)
        root.deiconify()
        # Toplevel을 메인으로 전환
        win.root.protocol("WM_DELETE_WINDOW", lambda: (win.root.destroy(), root.destroy()))
        root.mainloop()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


if __name__ == "__main__":
    win = SettingsWindow()
    win.show()
