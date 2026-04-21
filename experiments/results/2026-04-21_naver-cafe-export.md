# 2026-04-21 Naver Cafe Export

## Goal

Reduce manual cleanup when copying the generated report into Naver Cafe by adding a dedicated paste-friendly HTML fragment to the report page.

## Changes

- Added `_render_naver_cafe_html()` in `pipeline/summarizer.py`.
- Added a new `네이버 카페 붙여넣기` card to the generated report HTML.
- Added `HTML 복사` clipboard support with `text/html` plus `text/plain` fallback.
- Kept the existing `원본 요약 마크다운 보기` fallback unchanged for debugging/raw access.
- Added `experiments/test_naver_cafe_export.py` to verify the card, template, and clipboard hook are emitted.

## Verification

Commands run:

```powershell
python -m py_compile pipeline/summarizer.py experiments/test_naver_cafe_export.py
python experiments/test_naver_cafe_export.py
python -c "from pipeline.summarizer import _generate_html; print('ok')"
rg -n "네이버 카페 붙여넣기|naverCafeTemplate|copyNaverCafeHtml|원본 요약 마크다운 보기" output/12702452_naver_export_preview.html -S
```

Observed results:

- `py_compile` passed. A pre-existing `SyntaxWarning` about an invalid escape sequence was reported from `pipeline/summarizer.py`, but compilation succeeded.
- `experiments/test_naver_cafe_export.py` rendered `output/12702452_naver_export_preview.html` and verified 5 required tokens.
- Direct import smoke passed with `ok`.
- Rendered preview contains:
  - `네이버 카페 붙여넣기`
  - `copyNaverCafeHtml`
  - `naverCafeTemplate`
  - existing `원본 요약 마크다운 보기`

## Notes

- The new export block uses simple semantic HTML (`h2`, `p`, `blockquote`, `hr`, `a`) rather than Naver's internal `se-*` DOM. That keeps generation stable while producing cleaner clipboard HTML for the editor to ingest.
- The test preview file is `output/12702452_naver_export_preview.html`.
