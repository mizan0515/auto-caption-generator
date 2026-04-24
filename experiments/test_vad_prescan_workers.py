import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from transcribe import resolve_vad_prescan_workers


def main():
    cases = [
        {"n_parts": 0, "configured": None, "expected": 1},
        {"n_parts": 1, "configured": None, "expected": 1},
        {"n_parts": 9, "configured": None, "expected": 1},
        {"n_parts": 9, "configured": 4, "expected": 4},
        {"n_parts": 2, "configured": 4, "expected": 2},
        {"n_parts": 5, "configured": 0, "expected": 1},
    ]

    for case in cases:
        actual = resolve_vad_prescan_workers(
            case["n_parts"],
            configured_workers=case["configured"],
        )
        assert actual == case["expected"], (case, actual)
        print(
            f"ok n_parts={case['n_parts']} configured={case['configured']} -> {actual}"
        )


if __name__ == "__main__":
    main()
