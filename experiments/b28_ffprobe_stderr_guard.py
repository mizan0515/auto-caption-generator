from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from split_video import get_duration


class DummyResult:
    def __init__(self, returncode, stdout=None, stderr=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def main():
    with mock.patch("split_video.subprocess.run", return_value=DummyResult(1, stdout=None, stderr=None)):
        try:
            get_duration("dummy.mp4")
        except RuntimeError as exc:
            message = str(exc)
            assert "ffprobe failed" in message, message
            assert "(ffprobe output unavailable)" in message, message
            assert "dummy.mp4" in message, message
        else:
            raise AssertionError("expected RuntimeError for ffprobe failure")

    with mock.patch("split_video.subprocess.run", return_value=DummyResult(0, stdout="not-a-number", stderr="")):
        try:
            get_duration("dummy.mp4")
        except RuntimeError as exc:
            message = str(exc)
            assert "non-numeric duration" in message, message
        else:
            raise AssertionError("expected RuntimeError for non-numeric duration")

    print("PASS: ffprobe stderr/stdout guard regression checks")


if __name__ == "__main__":
    main()
