# B29 m3u8 map slice smoke

## Goal

Verify that m3u8 slice downloads remain valid after:

- preserving `#EXT-X-MAP` init segments
- rejecting corrupt cached mp4 files before reuse
- fixing ffprobe stderr/stdout handling on Windows

## Command

`python experiments/b29_m3u8_map_slice_smoke.py 12801656 --start-sec 0 --duration-sec 300`

## Result

- PASS: `12801656` 5-minute slice downloaded successfully
- PASS: `split_video.get_duration()` returned `303.90s`

## Notes

The previously cached full mp4 for `12801656` was invalid and now gets treated as a corrupt cache instead of being silently reused.
