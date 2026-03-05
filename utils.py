"""공통 유틸리티 — 파일 다이얼로그, SRT 파일 읽기"""

import streamlit as st


def pick_file(multiple: bool = False, filetypes=None):
    """tkinter 파일 다이얼로그로 파일 경로를 반환한다.

    multiple=True: 여러 파일 선택 → list[str]
    multiple=False: 단일 파일 → str
    filetypes: [(label, pattern), ...] 형식. None이면 모든 파일.
    """
    import tkinter as tk
    from tkinter import filedialog

    if filetypes is None:
        filetypes = [("모든 파일", "*.*")]

    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)

        if multiple:
            result = list(filedialog.askopenfilenames(filetypes=filetypes))
        else:
            result = filedialog.askopenfilename(filetypes=filetypes) or ""
    except Exception as e:
        st.warning(f"파일 다이얼로그 오류: {e}")
        result = [] if multiple else ""
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    return result


def pick_directory():
    """tkinter 폴더 다이얼로그로 디렉터리 경로를 반환한다."""
    import tkinter as tk
    from tkinter import filedialog

    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        result = filedialog.askdirectory() or ""
    except Exception as e:
        st.warning(f"폴더 다이얼로그 오류: {e}")
        result = ""
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    return result


def read_srt_text(path: str) -> str | None:
    """SRT 파일을 텍스트로 읽는다. 인코딩 자동 감지 (utf-8 → utf-16 → cp949 → latin-1).

    반환: 파일 내용 문자열, 실패 시 None.
    """
    for encoding in ("utf-8", "utf-16", "cp949", "latin-1"):
        try:
            with open(path, encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as e:
            st.error(f"파일을 읽을 수 없습니다: {e}")
            return None

    st.error(f"파일 인코딩을 인식할 수 없습니다: {path}")
    return None
