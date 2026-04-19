# B27 Long VOD Slice Smoke

Date: 2026-04-19

## Goal

Verify that a long VOD can be processed as a bounded slice instead of a single full-length run.

## Command

```powershell
python -m pipeline.main --process 12752012 --start-offset 0 --limit-duration 300
```

## Result

- PASS
- Existing full mp4 cache in `work/12752012/` was reused and clipped into a 5-minute slice.
- Slice transcription, chunk summarization, markdown/html report generation, and publish hook all completed.

## Output

- `output/12752012_20260415_아무튼 새로 태어난 나 호종컵 대기중.. ٩(●'▿'●)۶  [000000-000500].md`
- `output/12752012_20260415_아무튼 새로 태어난 나 호종컵 대기중.. ٩(●'▿'●)۶  [000000-000500].html`

## Notes

- This run still loaded Whisper and Claude for the selected slice, but it no longer required an 11-hour monolithic job before the first report could appear.
