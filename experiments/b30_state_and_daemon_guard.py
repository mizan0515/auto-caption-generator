from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.main import _acquire_daemon_lock, _release_daemon_lock
from pipeline.state import PipelineState


def test_completed_state_regression_guard(tmpdir: str) -> None:
    state = PipelineState(str(Path(tmpdir) / "state.json"))
    channel_id = "channel"
    video_no = "video"

    state.update(video_no, "completed", channel_id=channel_id, output_md="done.md")
    state.update(video_no, "summarizing", channel_id=channel_id, error="late worker")

    entry = state._load()["processed_vods"][f"{channel_id}:{video_no}"]
    assert entry["status"] == "completed", entry
    assert entry["output_md"] == "done.md", entry


def test_daemon_single_instance_lock(tmpdir: str) -> None:
    lock_path = str(Path(tmpdir) / "pipeline_daemon.lock")
    fd1 = _acquire_daemon_lock(lock_path)
    assert fd1 is not None
    fd2 = _acquire_daemon_lock(lock_path)
    assert fd2 is None
    _release_daemon_lock(fd1)

    fd3 = _acquire_daemon_lock(lock_path)
    assert fd3 is not None
    _release_daemon_lock(fd3)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_completed_state_regression_guard(tmpdir)
        test_daemon_single_instance_lock(tmpdir)
    print("PASS: completed-state regression + daemon single-instance guard")


if __name__ == "__main__":
    main()
