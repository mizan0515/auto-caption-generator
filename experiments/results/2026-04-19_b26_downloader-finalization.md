# B26 Downloader Finalization Guard

Date: 2026-04-19

## Goal

Verify that the 144p downloader:

1. Promotes `.downloading` to the final `.mp4` after a successful download.
2. Recovers a completed stale `.downloading` file on the next run instead of deleting it.

## Command

```powershell
python experiments\b26_downloader_finalization_guard.py
```

## Result

- PASS
- `_download_m3u8()` wrote the final file and removed the temp suffix.
- `download_vod_144p()` recovered an existing non-empty `.downloading` file into the final `.mp4`.
- `_download_m3u8(start_sec=..., duration_sec=...)` selected only the requested segment range.

## Notes

- This guards the regression that left long VODs stuck with only `.downloading`, which in turn blocked summary generation.
