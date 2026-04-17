"""원클릭 셋업/런치 — 의존성·외부 도구·설정을 점검하고 누락된 것만 사용자에게 안내.

사용법:
    python scripts/first_run.py          # 체크 + 필요 시 대화형 설치/설정 → 트레이 실행
    python scripts/first_run.py --check  # 체크만, 설치/실행 안 함 (CI용)
    python scripts/first_run.py --no-launch  # 체크 통과해도 트레이 실행 안 함

체크 항목 (순서대로):
1. Python >= 3.10
2. pip 의존성 (requirements.txt)  — 누락 시 `pip install -r requirements.txt` 자동 실행
3. ffmpeg (PATH)                  — 누락 시 winget 명령 안내
4. claude CLI (PATH)              — 누락 시 설치 URL 안내
5. wrangler CLI (PATH, 선택)      — publish_autodeploy=true 일 때만 강제
6. pipeline_config.json 존재 + 필수 필드 (채널 ID, 쿠키)
   - 없으면 설정 GUI 실행
7. 쿠키 비어있으면 browser_cookie3 로 자동 추출 시도

성공 시 `pythonw tray_app.py` 를 detached 로 런치.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from pipeline._io_encoding import force_utf8_stdio  # type: ignore

    force_utf8_stdio()
except Exception:  # noqa: BLE001
    pass


# ANSI 이스케이프 없이 순수 ASCII 라벨만 사용 (Windows cmd 호환)
def _pr(status: str, msg: str) -> None:
    print(f"  [{status}] {msg}")


def _ok(msg: str) -> None:
    _pr("OK ", msg)


def _warn(msg: str) -> None:
    _pr("!! ", msg)


def _err(msg: str) -> None:
    _pr("XX ", msg)


def _section(title: str) -> None:
    print(f"\n== {title} ==")


def check_python() -> bool:
    _section("1. Python 버전")
    v = sys.version_info
    if v < (3, 10):
        _err(f"Python {v.major}.{v.minor} 감지 — 3.10 이상 필요")
        print("     https://www.python.org/downloads/ 에서 최신 설치 후 재시도")
        return False
    _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    return True


def check_pip_deps(auto_install: bool) -> bool:
    _section("2. Python 의존성 (requirements.txt)")
    req = PROJECT_ROOT / "requirements.txt"
    if not req.exists():
        _err(f"requirements.txt 없음: {req}")
        return False

    # 빠른 import 체크 — 느린 torch 는 제외하고 주요 패키지만
    probes = [
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
        ("pystray", "pystray"),
        ("PIL", "Pillow"),
        ("browser_cookie3", "browser_cookie3"),
    ]
    missing = []
    for mod, pkg in probes:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)

    if not missing:
        _ok("핵심 패키지 임포트 통과 (torch/transformers 는 첫 실행 시 로드 확인)")
        return True

    _warn(f"누락: {', '.join(missing)}")
    if not auto_install:
        print("     $ pip install -r requirements.txt")
        return False

    print("     자동으로 `pip install -r requirements.txt` 실행...")
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "-r", str(req)])
    if rc != 0:
        _err(f"pip install 실패 (exit={rc})")
        return False
    _ok("pip install 완료")
    return True


def check_ffmpeg() -> bool:
    _section("3. ffmpeg")
    if shutil.which("ffmpeg"):
        _ok("ffmpeg PATH 에 등록됨")
        return True
    _err("ffmpeg 미등록")
    print("     Windows: winget install Gyan.FFmpeg")
    print("     macOS:   brew install ffmpeg")
    print("     수동:    https://ffmpeg.org/download.html")
    return False


def check_claude_cli() -> bool:
    _section("4. Claude Code CLI")
    if shutil.which("claude"):
        _ok("claude PATH 에 등록됨")
        return True
    _err("claude CLI 미등록")
    print("     https://docs.claude.com/claude-code 참고해서 설치 후 PATH 등록")
    return False


def check_wrangler(required: bool) -> bool:
    _section("5. wrangler CLI (Cloudflare Pages 배포용)")
    if shutil.which("wrangler"):
        _ok("wrangler PATH 에 등록됨")
        return True
    msg = "wrangler 미등록 — publish_autodeploy 기능 비활성"
    if required:
        _err(msg + " (publish_autodeploy=true 지만 없음)")
        print("     $ npm install -g wrangler && wrangler login")
        return False
    _warn(msg)
    print("     자동 배포 쓰려면: npm install -g wrangler && wrangler login")
    return True  # 선택이므로 통과


def check_config_and_cookies(auto_refresh_cookies: bool) -> tuple[bool, bool]:
    """
    Returns:
        (ok, needs_settings_ui) — ok=True 여야 진행, needs_settings_ui=True 면 GUI 호출
    """
    _section("6. pipeline_config.json")
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from pipeline.config import load_config, _resolve_config_path  # type: ignore
    except Exception as e:  # noqa: BLE001
        _err(f"pipeline.config 로드 실패: {e}")
        return False, False

    cfg_path = _resolve_config_path(None)
    if not cfg_path.exists():
        _warn(f"설정 파일 없음 — {cfg_path} (기본값으로 생성 후 GUI 필요)")
        # load_config 가 없으면 DEFAULT 로 생성함
        load_config()
        return True, True

    try:
        cfg = load_config()
    except Exception as e:  # noqa: BLE001
        _err(f"설정 유효성 검사 실패: {e}")
        return False, True

    # 필수: channel_id
    streamers = cfg.get("streamers")
    has_channel = bool(cfg.get("target_channel_id")) or (
        isinstance(streamers, list) and any(s.get("channel_id") for s in streamers)
    )
    if not has_channel:
        _warn("스트리머 채널 ID 미설정")
        return True, True
    _ok("스트리머 채널 설정 감지")

    # 쿠키
    cookies = cfg.get("cookies") or {}
    has_cookies = bool(cookies.get("NID_AUT")) and bool(cookies.get("NID_SES"))
    if has_cookies:
        _ok("NID_AUT/NID_SES 설정 감지")
        return True, False

    _warn("쿠키 비어있음")
    if auto_refresh_cookies:
        print("     브라우저에서 자동 추출 시도...")
        try:
            from pipeline.cookie_refresh import refresh_cookies  # type: ignore

            ok, reason = refresh_cookies()
            if ok:
                _ok(f"쿠키 갱신 성공 — {reason}")
                return True, False
            _warn(f"자동 추출 실패 — {reason}")
        except Exception as e:  # noqa: BLE001
            _warn(f"자동 추출 예외 — {e}")

    print("     트레이 메뉴 '쿠키 새로고침' 또는 설정 GUI 에서 수동 입력 가능")
    return True, True


def open_settings_ui() -> bool:
    _section("7. 설정 GUI")
    print("     설정 창이 열립니다. 저장 후 창을 닫으세요.")
    try:
        from pipeline.settings_ui import open_settings  # type: ignore

        saved = {"flag": False}

        def _on_save(_cfg):
            saved["flag"] = True

        open_settings(on_save=_on_save)
        if saved["flag"]:
            _ok("설정 저장됨")
            return True
        _warn("설정 창이 닫혔지만 저장되지 않음")
        return False
    except Exception as e:  # noqa: BLE001
        _err(f"설정 GUI 실행 실패: {e}")
        return False


def launch_tray() -> bool:
    _section("8. 트레이 앱 실행")
    pythonw = shutil.which("pythonw") or sys.executable.replace("python.exe", "pythonw.exe")
    tray = PROJECT_ROOT / "tray_app.py"
    if not tray.exists():
        _err(f"tray_app.py 없음: {tray}")
        return False
    try:
        # Detached 실행 — 이 프로세스가 끝나도 트레이는 계속
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        subprocess.Popen(
            [pythonw, str(tray)],
            cwd=str(PROJECT_ROOT),
            creationflags=creationflags,
            close_fds=True,
        )
        _ok("트레이 아이콘을 확인하세요 (Windows 작업표시줄 오른쪽)")
        return True
    except Exception as e:  # noqa: BLE001
        _err(f"트레이 실행 실패: {e}")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="원클릭 셋업 + 런치")
    parser.add_argument("--check", action="store_true", help="체크만 (자동 설치·실행 없음)")
    parser.add_argument("--no-launch", action="store_true", help="체크 통과해도 트레이 실행 안 함")
    parser.add_argument("--no-install", action="store_true", help="pip install 자동 실행 금지")
    parser.add_argument(
        "--no-refresh-cookies", action="store_true", help="쿠키 자동 추출 시도 안 함"
    )
    args = parser.parse_args(argv)

    auto_install = not args.no_install and not args.check
    auto_cookies = not args.no_refresh_cookies and not args.check

    print("=" * 60)
    print(" Chzzk VOD 파이프라인 — 환경 점검")
    print("=" * 60)

    results = []
    results.append(("python", check_python()))
    if not results[-1][1]:
        return 1
    results.append(("deps", check_pip_deps(auto_install=auto_install)))
    results.append(("ffmpeg", check_ffmpeg()))
    results.append(("claude", check_claude_cli()))

    # publish_autodeploy 활성 여부에 따라 wrangler 강제
    need_wrangler = False
    try:
        from pipeline.config import load_config  # type: ignore

        cfg_for_wrangler = (
            load_config() if (PROJECT_ROOT / "pipeline_config.json").exists() else {}
        )
        need_wrangler = bool(cfg_for_wrangler.get("publish_autodeploy"))
    except Exception:  # noqa: BLE001
        pass
    results.append(("wrangler", check_wrangler(required=need_wrangler)))

    cfg_ok, needs_gui = check_config_and_cookies(auto_refresh_cookies=auto_cookies)
    results.append(("config", cfg_ok))

    if needs_gui and not args.check:
        if not open_settings_ui():
            return 2
        # GUI 후 쿠키 재점검 — 사용자가 GUI 에서 입력했을 수 있음
        cfg_ok2, _ = check_config_and_cookies(auto_refresh_cookies=False)
        if not cfg_ok2:
            _err("설정 재검증 실패")
            return 2

    print()
    print("=" * 60)
    failed = [k for k, ok in results if not ok]
    if failed:
        _err(f"실패 항목: {', '.join(failed)}")
        print("     위 안내를 따라 해결 후 다시 실행하세요.")
        return 3
    _ok("모든 점검 통과")

    if args.check or args.no_launch:
        return 0

    if not launch_tray():
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
