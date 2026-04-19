# B28 ffprobe stderr guard

## Goal

Prevent `split_video.get_duration()` from masking the real ffprobe failure with `AttributeError` when `subprocess.run(...).stderr` is `None`.

## Changes

- Normalized `stdout` and `stderr` with `(value or "").strip()` in `split_video.py`
- Added fallback detail text when ffprobe returns no output at all
- Added explicit non-numeric duration guard

## Verification

- `python -m py_compile split_video.py experiments/b28_ffprobe_stderr_guard.py`
- `python experiments/b28_ffprobe_stderr_guard.py`

## Result

- PASS: ffprobe failure with `stderr=None` now raises a stable `RuntimeError`
- PASS: malformed ffprobe duration output now raises a clear `RuntimeError`

## Impact

The pipeline will now report the underlying ffprobe/media problem instead of crashing inside error formatting. This unblocks proper diagnosis of Whisper-stage failures for long VODs such as `12801656`.
