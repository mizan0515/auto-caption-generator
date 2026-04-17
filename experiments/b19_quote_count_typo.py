"""B19 offline verification - subtitle_analyzer quote_count 중복 집계 버그 수정.

pipeline/subtitle_analyzer.py _score_text() 의 인용문 집계가
  quote_count = text.count('"') // 2 + text.count('"') // 2 + text.count("'") // 2
이었는데, 첫 두 항이 같은 ASCII 쌍따옴표를 두 번 집계하여 ASCII 인용문이
2배로 점수화되던 버그. curly quotes 는 전혀 집계되지 않았음.

수정 후:
- ASCII "  → 1회
- Unicode " " (U+201C/U+201D) → 1회
- ASCII ' + Unicode ' ' (U+2018/U+2019) → 묶어서 단일 인용 집계
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline._io_encoding import force_utf8_stdio  # noqa: E402

force_utf8_stdio()

from pipeline.subtitle_analyzer import _score_text  # noqa: E402


def _quotes_only(text: str) -> int:
    """quote detail 만 추출 (다른 시그널 없는 텍스트 전제)."""
    _score, detail = _score_text(text)
    return detail["quotes"]


def _run_case(name: str, text: str, expected: int) -> bool:
    got = _quotes_only(text)
    if got == expected:
        print(f"[{name}] PASS - quotes={got} (text={text!r})")
        return True
    print(f"[{name}] FAIL - expected {expected}, got {got} (text={text!r})")
    return False


def main() -> int:
    results = [
        # ASCII 쌍따옴표 1쌍 = 1 quote (이전엔 버그로 2)
        _run_case("ascii_double_one_pair", '그가 "진실"이라 말했다', 1),
        # ASCII 쌍따옴표 2쌍 = 2 quotes (이전엔 버그로 4)
        _run_case("ascii_double_two_pairs", '"진짜" 그리고 "정말"', 2),
        # Curly double quote (이전엔 0, 이제 1)
        _run_case("curly_double_one_pair", "그는 \u201c끝났다\u201d 라고 했다", 1),
        # Mixed ASCII + curly double: 2쌍 합산
        _run_case("mixed_ascii_curly_double", '"A" 와 \u201cB\u201d', 2),
        # Single quote + curly single 묶음
        _run_case("mixed_single_and_curly_single", "'q' 그리고 \u2018r\u2019", 2),
        # 인용 없음
        _run_case("no_quotes", "그냥 평범한 문장입니다", 0),
        # 홀수 ASCII 쌍따옴표 → floor(3/2) = 1
        _run_case("odd_ascii_double", '"a "b" c', 1),
    ]

    # score 회귀: 이전 버그에서는 ASCII 쌍따옴표 1쌍 → quote_count=2 → score +=1.0
    # 수정 후: quote_count=1 → score +=0.5
    score_only, _ = _score_text('그는 "끝"이라 말했다')
    if abs(score_only - 0.5) < 1e-9:
        print(f"[ascii_pair_score] PASS - score={score_only} (bug previously gave 1.0)")
        results.append(True)
    else:
        print(f"[ascii_pair_score] FAIL - expected 0.5, got {score_only}")
        results.append(False)

    passed = sum(results)
    total = len(results)
    print(f"\nB19 verification: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
