"""recorrect_reports 의 _parse_replacements / _apply_replacements 회귀 락.

실행: python experiments/test_recorrect_apply.py
실패 시 비-0 exit code + 메시지.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.recorrect_reports import _parse_replacements, _apply_replacements


_failures: list[str] = []


def _check(name: str, got, want):
    if got != want:
        _failures.append(f"  {name}\n    got : {got!r}\n    want: {want!r}")


# ── _parse_replacements ─────────────────────────────────────────

# 1. 코드펜스 + 정상 JSON
r1 = """```json
{"replacements": [{"old":"삐구","new":"삐부"},{"old":"따윤희","new":"따효니"}]}
```"""
_check("parse:fence+ok", _parse_replacements(r1),
       [("삐구", "삐부"), ("따윤희", "따효니")])

# 2. 빈 리스트
_check("parse:empty",
       _parse_replacements('{"replacements": []}'), [])

# 3. 가비지
_check("parse:garbage", _parse_replacements("응 못 고치겠어"), [])

# 4. 코드펜스 없는 JSON
_check("parse:no-fence",
       _parse_replacements('{"replacements":[{"old":"a","new":"b"}]}'),
       [("a", "b")])

# 5. old == new 는 무시
_check("parse:identity-skip",
       _parse_replacements('{"replacements":[{"old":"x","new":"x"},{"old":"a","new":"b"}]}'),
       [("a", "b")])

# 6. 빈 old 무시
_check("parse:empty-old",
       _parse_replacements('{"replacements":[{"old":"","new":"y"}]}'),
       [])

# 7. 너무 긴 old (>30) 무시
_check("parse:too-long",
       _parse_replacements('{"replacements":[{"old":"' + "가" * 31 + '","new":"b"}]}'),
       [])

# 8. dict 가 아닌 항목 skip
_check("parse:non-dict-skip",
       _parse_replacements('{"replacements":["string","also",{"old":"a","new":"b"}]}'),
       [("a", "b")])

# 9. 주변 텍스트 + JSON
_check("parse:surrounded",
       _parse_replacements('아 결과는: {"replacements":[{"old":"a","new":"b"}]} 입니다.'),
       [("a", "b")])


# ── _apply_replacements ─────────────────────────────────────────

new, applied = _apply_replacements(
    "오늘 삐구가 따윤희랑 게임. 삐구는 또 던졌다.",
    [("삐구", "삐부"), ("따윤희", "따효니"), ("없는것", "있는것")],
)
_check("apply:result", new, "오늘 삐부가 따효니랑 게임. 삐부는 또 던졌다.")
_check("apply:counts", applied,
       [("삐구", "삐부", 2), ("따윤희", "따효니", 1), ("없는것", "있는것", 0)])

# 빈 매핑
new, applied = _apply_replacements("hello", [])
_check("apply:empty", new, "hello")
_check("apply:empty-applied", applied, [])

# old 가 new 의 부분문자열인 경우 (확장 위험 없음 — str.replace 는 1패스)
new, applied = _apply_replacements("aaa", [("a", "ab")])
_check("apply:expansion-safe", new, "ababab")


# ── 결과 ──────────────────────────────────────────────────────

if _failures:
    print(f"FAIL ({len(_failures)} 건)")
    for f in _failures:
        print(f)
    sys.exit(1)

print("OK — 모든 케이스 통과")
