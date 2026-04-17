"""B17 offline verification - m3u8 base URL 파서 IndexError 방어 검증.

content/network.py의 get_video_m3u8_base_url() 이 RESOLUTION 매칭 라인이
m3u8 응답의 마지막 라인인 경우 IndexError 대신 명시적 ValueError 를
발생시키는지 확인한다.

requests.get 을 monkeypatch 하여 오프라인에서 실행한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline._io_encoding import force_utf8_stdio  # noqa: E402

force_utf8_stdio()

from content import network as net  # noqa: E402


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _run_case(name: str, m3u8_text: str, resolution: int, *, expect_error: bool, expected_base: str | None = None):
    original_get = net.requests.get
    try:
        net.requests.get = lambda *a, **kw: _FakeResponse(m3u8_text)  # type: ignore[assignment]
        json_str = json.dumps({"media": [{"path": "https://example.invalid/master.m3u8"}]})
        try:
            result = net.NetworkManager.get_video_m3u8_base_url(json_str, resolution)
        except ValueError as e:
            if expect_error:
                print(f"[{name}] PASS - ValueError raised: {e}")
                return True
            print(f"[{name}] FAIL - unexpected ValueError: {e}")
            return False
        except IndexError as e:
            print(f"[{name}] FAIL - IndexError leaked (regression): {e}")
            return False
        else:
            if expect_error:
                print(f"[{name}] FAIL - expected ValueError, got {result!r}")
                return False
            if expected_base and not result.startswith(expected_base):
                print(f"[{name}] FAIL - base_url mismatch: {result!r}")
                return False
            print(f"[{name}] PASS - base_url={result}")
            return True
    finally:
        net.requests.get = original_get


def main() -> int:
    # 정상 케이스: RESOLUTION 뒤에 경로 줄 존재
    ok_text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720\n"
        "720p/playlist.m3u8\n"
    )
    # 회귀 케이스: RESOLUTION 매칭이 마지막 라인 (다음 경로 줄 없음)
    trailing_text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720"
    )
    # 빈 경로 케이스
    empty_path_text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720\n"
        "   \n"
    )
    # 미매칭 케이스
    no_match_text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1920x1080\n"
        "1080p/playlist.m3u8\n"
    )

    results = [
        _run_case("happy_path", ok_text, 720, expect_error=False, expected_base="https://example.invalid/"),
        _run_case("trailing_resolution_regression", trailing_text, 720, expect_error=True),
        _run_case("empty_next_line", empty_path_text, 720, expect_error=True),
        _run_case("no_match", no_match_text, 720, expect_error=True),
    ]

    passed = sum(results)
    total = len(results)
    print(f"\nB17 verification: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
