import os
import sys
import tempfile
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pipeline import downloader as dl


class _FakeResponse:
    def __init__(self, *, text=None, chunks=None, status_code=200):
        self.text = text or ""
        self._chunks = chunks or []
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def iter_content(self, chunk_size=8192):
        del chunk_size
        for chunk in self._chunks:
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@contextmanager
def _patched_requests_get():
    original_get = dl.requests.get

    def fake_get(url, headers=None, timeout=None, stream=False):
        del headers, timeout, stream
        if url.endswith("playlist.m3u8"):
            return _FakeResponse(
                text="#EXTM3U\n#EXTINF:5.0,\nseg0.ts\n#EXTINF:5.0,\nseg1.ts\n"
            )
        if url.endswith("seg0.ts"):
            return _FakeResponse(chunks=[b"hello", b"-"])
        if url.endswith("seg1.ts"):
            return _FakeResponse(chunks=[b"world"])
        raise AssertionError(f"unexpected url: {url}")

    dl.requests.get = fake_get
    try:
        yield
    finally:
        dl.requests.get = original_get


@contextmanager
def _patched_video_info():
    original = dl.NetworkManager.get_video_info

    def fake_get_video_info(video_no, cookies):
        del cookies
        return ("video-id", "in-key", False, "PUBLIC", None, {"title": f"title-{video_no}"})

    dl.NetworkManager.get_video_info = fake_get_video_info
    try:
        yield
    finally:
        dl.NetworkManager.get_video_info = original


def test_m3u8_finalizes_to_dest() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, _patched_requests_get():
        dest = os.path.join(tmpdir, "sample.mp4")
        returned = dl._download_m3u8("https://example.com/path/playlist.m3u8", dest)
        assert returned == dest
        assert os.path.isfile(dest), "final mp4 missing"
        assert not os.path.exists(dest + ".downloading"), "temp file should be removed"
        with open(dest, "rb") as fh:
            assert fh.read() == b"hello-world"


def test_stale_tmp_is_recovered() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, _patched_video_info():
        dest = os.path.join(tmpdir, "vod123_title-vod123_144p.mp4")
        tmp_path = dest + ".downloading"
        with open(tmp_path, "wb") as fh:
            fh.write(b"already-downloaded")

        returned = dl.download_vod_144p("vod123", {}, tmpdir)
        assert returned == dest
        assert os.path.isfile(dest), "recovered final mp4 missing"
        assert not os.path.exists(tmp_path), "recovery should rename temp file"
        with open(dest, "rb") as fh:
            assert fh.read() == b"already-downloaded"


def test_m3u8_slice_selection() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, _patched_requests_get():
        dest = os.path.join(tmpdir, "slice.mp4")
        returned = dl._download_m3u8(
            "https://example.com/path/playlist.m3u8",
            dest,
            start_sec=5,
            duration_sec=5,
        )
        assert returned == dest
        with open(dest, "rb") as fh:
            assert fh.read() == b"world"


def main() -> None:
    test_m3u8_finalizes_to_dest()
    test_stale_tmp_is_recovered()
    test_m3u8_slice_selection()
    print("PASS b26_downloader_finalization_guard")


if __name__ == "__main__":
    main()
