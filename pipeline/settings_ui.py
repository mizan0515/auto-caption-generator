"""파이프라인 설정 GUI (tkinter)

트레이 앱 또는 독립 실행으로 pipeline_config.json을 편집.

멀티 스트리머 모드:
    - 한 화면에서 여러 스트리머를 추가/수정/삭제할 수 있다.
    - 저장 시 cfg["streamers"] 가 canonical form 으로 직렬화되며
      `pipeline.config.normalize_streamers()` 가 그대로 소비할 수 있다.
    - legacy 호환을 위해 첫 번째 스트리머는 `target_channel_id`,
      `streamer_name`, `fmkorea_search_keywords` 로도 미러링된다.
"""

import json
import re
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from .config import load_config, save_config, _config_path, normalize_streamers


# ── 필드 정의: (config key, 라벨, 타입, 설명) ──
# 스트리머 관련 필드 (streamer_name, target_channel_id, fmkorea_search_keywords)
# 는 별도 멀티 스트리머 섹션에서 관리한다.
FIELDS = [
    # 기본 설정 (스트리머 외)
    ("poll_interval_sec",    "폴링 간격 (초)",      "int",   "새 VOD 확인 주기 (기본: 300초 = 5분)"),
    ("download_resolution",  "다운로드 해상도",     "int",   "VOD 다운로드 해상도 (기본: 144)"),
    ("bootstrap_mode",       "Bootstrap 모드",     "str",   "최초 실행 시 정책: 빈칸(질문) / skip_all / latest_n"),
    ("bootstrap_latest_n",   "Bootstrap 최신 N개",  "int",   "latest_n 모드일 때 처리할 개수"),

    # 커뮤니티
    ("fmkorea_enabled",      "fmkorea 수집",       "bool",  "fmkorea 커뮤니티 스크레이핑 활성화"),
    ("fmkorea_max_pages",    "최대 페이지",         "int",   "키워드당 검색 페이지 수"),
    ("fmkorea_max_posts",    "최대 게시글",         "int",   "수집할 최대 게시글 수"),

    # 자막/요약
    ("chunk_max_chars",      "청크 최대 글자",      "int",   "SRT 청크 분할 기준 (기본: 8000)"),
    ("chunk_overlap_sec",    "청크 오버랩 (초)",    "int",   "청크 간 겹침 구간 (기본: 30)"),
    ("claude_timeout_sec",   "Claude 타임아웃 (초)","int",   "Claude CLI 호출 제한시간"),

    # 경로
    ("output_dir",           "출력 디렉터리",       "str",   "리포트 저장 경로"),
    ("work_dir",             "작업 디렉터리",       "str",   "임시 파일 저장 경로"),
    ("auto_cleanup",         "자동 정리",           "bool",  "처리 완료 후 임시 파일 삭제"),
]

# 섹션 분할 인덱스
BASIC_END = 4        # 기본 설정 0..3
COMMUNITY_END = 7    # 커뮤니티 4..6
CHUNK_END = 10       # 자막/요약 7..9
# 경로 10..

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
        # 멀티 스트리머 row 관리: 각 항목은 dict
        #   {"frame": ttk.Frame, "channel_id": Entry, "name": Entry, "keywords": Entry}
        self.streamer_rows = []

        if parent:
            self.root = tk.Toplevel(parent)
        else:
            self.root = tk.Tk()

        self.root.title("파이프라인 설정")
        self.root.geometry("680x780")
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

        # ── 멀티 스트리머 ──
        row = self._add_section("스트리머 (멀티 스트리머 지원)", row)
        ttk.Label(
            self.frame,
            text="여러 스트리머를 동시에 모니터링할 수 있습니다. 각 행: 채널 ID(32자리 hex), 이름, 검색 키워드(쉼표 구분).",
            foreground="gray",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 4))
        row += 1

        # streamers 목록 컨테이너 (rows 가 동적으로 추가/제거됨)
        self.streamers_container = ttk.Frame(self.frame)
        self.streamers_container.grid(row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 4))
        row += 1

        # "+ 스트리머 추가" 버튼
        add_btn = ttk.Button(self.frame, text="+ 스트리머 추가", command=self._on_add_streamer)
        add_btn.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 6))
        row += 1

        # ── 기본 설정 ──
        row = self._add_section("기본 설정", row)
        for key, label, ftype, desc in FIELDS[:BASIC_END]:
            row = self._add_field(key, label, ftype, desc, row)

        # ── 커뮤니티 설정 ──
        row = self._add_section("커뮤니티 수집", row)
        for key, label, ftype, desc in FIELDS[BASIC_END:COMMUNITY_END]:
            row = self._add_field(key, label, ftype, desc, row)

        # ── 자막/요약 설정 ──
        row = self._add_section("자막 / 요약", row)
        for key, label, ftype, desc in FIELDS[COMMUNITY_END:CHUNK_END]:
            row = self._add_field(key, label, ftype, desc, row)

        # ── 경로 설정 ──
        row = self._add_section("경로 / 정리", row)
        for key, label, ftype, desc in FIELDS[CHUNK_END:]:
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

    # ── 멀티 스트리머 row 관리 ──

    def _on_add_streamer(self):
        """'+ 스트리머 추가' 버튼 콜백."""
        self._add_streamer_row({"channel_id": "", "name": "", "search_keywords": []})

    def _add_streamer_row(self, streamer: dict) -> None:
        """streamers_container 에 한 행을 추가한다.

        streamer: {"channel_id": str, "name": str, "search_keywords": list[str]}
        """
        row_frame = ttk.LabelFrame(self.streamers_container, text=f"스트리머 #{len(self.streamer_rows) + 1}")
        row_frame.pack(fill="x", expand=True, pady=(0, 6))

        # 채널 ID
        ttk.Label(row_frame, text="채널 ID (32 hex):").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        cid_entry = ttk.Entry(row_frame, width=40)
        cid_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        cid_entry.insert(0, streamer.get("channel_id", "") or "")

        # 이름
        ttk.Label(row_frame, text="이름:").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        name_entry = ttk.Entry(row_frame, width=30)
        name_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        name_entry.insert(0, streamer.get("name", "") or "")

        # 검색 키워드
        ttk.Label(row_frame, text="검색 키워드 (쉼표):").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        kw_entry = ttk.Entry(row_frame, width=40)
        kw_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=2)
        keywords = streamer.get("search_keywords") or []
        if isinstance(keywords, list):
            kw_entry.insert(0, ", ".join(str(k) for k in keywords))
        else:
            kw_entry.insert(0, str(keywords))

        # 삭제 버튼
        del_btn = ttk.Button(row_frame, text="삭제", width=8)
        del_btn.grid(row=0, column=2, rowspan=3, sticky="ns", padx=8, pady=2)

        row_frame.columnconfigure(1, weight=1)

        row_dict = {
            "frame": row_frame,
            "channel_id": cid_entry,
            "name": name_entry,
            "keywords": kw_entry,
        }
        self.streamer_rows.append(row_dict)

        # 람다 캡처 — row_dict 자체를 인자로 넘긴다
        del_btn.configure(command=lambda r=row_dict: self._remove_streamer_row(r))

    def _remove_streamer_row(self, row_dict: dict) -> None:
        if row_dict not in self.streamer_rows:
            return
        if len(self.streamer_rows) <= 1:
            messagebox.showwarning(
                "삭제 불가",
                "최소 1명의 스트리머가 필요합니다."
            )
            return
        row_dict["frame"].destroy()
        self.streamer_rows.remove(row_dict)
        self._renumber_streamer_rows()

    def _renumber_streamer_rows(self) -> None:
        """삭제 후 LabelFrame 의 '스트리머 #N' 표시를 갱신한다."""
        for idx, row in enumerate(self.streamer_rows, start=1):
            row["frame"].configure(text=f"스트리머 #{idx}")

    def _clear_streamer_rows(self) -> None:
        for row in list(self.streamer_rows):
            row["frame"].destroy()
        self.streamer_rows = []

    def _collect_streamers(self) -> list[dict]:
        """row 위젯에서 streamers list 를 수집한다 (canonical form)."""
        result = []
        for row in self.streamer_rows:
            cid = row["channel_id"].get().strip()
            name = row["name"].get().strip()
            kw_raw = row["keywords"].get().strip()
            keywords = [s.strip() for s in kw_raw.split(",") if s.strip()]
            # 키워드 비어있으면 기본값으로 name 사용 (legacy 동작 보존)
            if not keywords and name:
                keywords = [name]
            result.append({
                "channel_id": cid,
                "name": name,
                "search_keywords": keywords,
            })
        return result

    @staticmethod
    def _is_valid_channel_id(channel_id: str) -> bool:
        """Chzzk channel_id 는 32자리 hex 문자열이어야 한다."""
        return bool(re.fullmatch(r"[0-9a-fA-F]{32}", channel_id))

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
        # 스트리머: legacy/multi 통합 normalize_streamers 로 1+ 행 생성
        self._clear_streamer_rows()
        streamers = normalize_streamers(self.cfg)
        if not streamers:
            streamers = [{"channel_id": "", "name": "", "search_keywords": []}]
        for s in streamers:
            self._add_streamer_row(s)

        # 일반 필드
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
                # None 은 빈 문자열로 표시
                widget.insert(0, "" if val is None else str(val))

        # 쿠키
        cookies = self.cfg.get("cookies", {})
        for key, _, _ in COOKIE_FIELDS:
            w = self.widgets[f"cookie_{key}"]
            w.delete(0, tk.END)
            w.insert(0, cookies.get(key, ""))

    def _collect_values(self) -> dict:
        """위젯에서 설정값 수집.

        반환:
            dict (성공) — `streamers` canonical list 와 legacy mirror 가 함께 들어감
            None (입력 오류 시 — 사용자에 메시지박스 표시 후 호출자 abort)
        """
        cfg = dict(self.cfg)

        # streamers
        streamers = self._collect_streamers()
        if not streamers:
            messagebox.showerror("입력 오류", "최소 1명의 스트리머를 입력해주세요.")
            return None

        # 검증: 채널 ID 와 이름이 있어야 한다 (모두 비어있는 행 거부)
        for idx, s in enumerate(streamers, start=1):
            if not s["channel_id"] and not s["name"]:
                messagebox.showerror(
                    "입력 오류",
                    f"스트리머 #{idx} 에 채널 ID 또는 이름을 입력해주세요."
                )
                return None
            if s["channel_id"] and not self._is_valid_channel_id(s["channel_id"]):
                if not messagebox.askyesno(
                    "경고",
                    f"스트리머 #{idx} 의 채널 ID 가 유효한 32자리 hex 가 아닙니다 "
                    f"({s['channel_id']!r}). 그대로 저장할까요?"
                ):
                    return None

        cfg["streamers"] = streamers

        # legacy mirror — 첫 스트리머를 scalar 필드에 동시 기록한다.
        #   - tray_app.py 의 상태 표시는 여전히 cfg["target_channel_id"] 를 본다.
        #   - publish/builder/build_site.py 는 metadata 우선, scalar 는 fallback.
        #   - main.py 의 일부 fallback 도 scalar 에 의존한다.
        first = streamers[0]
        cfg["target_channel_id"] = first["channel_id"]
        cfg["streamer_name"] = first["name"]
        cfg["fmkorea_search_keywords"] = list(first["search_keywords"])

        # 일반 필드
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
                raw = widget.get().strip()
                # bootstrap_mode 는 빈 문자열을 None 으로 정규화 (DEFAULT 와 일치)
                if key == "bootstrap_mode" and raw == "":
                    cfg[key] = None
                else:
                    cfg[key] = raw

        # 쿠키
        cfg["cookies"] = {}
        for key, _, _ in COOKIE_FIELDS:
            cfg["cookies"][key] = self.widgets[f"cookie_{key}"].get().strip()

        return cfg

    def _save(self):
        cfg = self._collect_values()
        if cfg is None:
            return

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
