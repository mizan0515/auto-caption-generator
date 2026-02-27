import argparse
import re
from datetime import timedelta
from pathlib import Path

'''
기본 실행:

python srt-preprocessing.py 1.srt

후보를 조금 더 많이(상위 15%) 뽑고, 패딩 60초로:

python masrt-preprocessingin.py 1.srt --top 0.15 --pad 60

출력 파일로 저장:

python srt-preprocessing.py 1.srt --out candidates.txt

'''






def parse_ts(ts: str) -> float:
    # "HH:MM:SS,mmm" -> seconds(float)
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def format_ts(sec: float) -> str:
    td = timedelta(seconds=max(0, sec))
    total = int(td.total_seconds())
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def load_srt(path: Path):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", raw.strip())
    items = []
    for b in blocks:
        lines = b.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.search(r"(\d\d:\d\d:\d\d,\d+)\s*-->\s*(\d\d:\d\d:\d\d,\d+)", lines[1])
        if not m:
            continue
        start = parse_ts(m.group(1))
        end = parse_ts(m.group(2))
        text = " ".join(lines[2:]).strip()
        if text:
            items.append((start, end, text))
    return items

def build_candidates(
    items,
    window_sec: int = 20,
    top_ratio: float = 0.10,
    pad_sec: int = 40,
    sample_lines: int = 10,
):
    start0 = min(s for s, _, _ in items)
    end0 = max(e for _, e, _ in items)

    n_bins = int((end0 - start0) // window_sec) + 1
    bins = [{"lines": 0, "chars": 0} for _ in range(n_bins)]

    # bin 집계: 시작 시간 기준으로 카운트
    for s, _, t in items:
        idx = int((s - start0) // window_sec)
        if 0 <= idx < n_bins:
            bins[idx]["lines"] += 1
            bins[idx]["chars"] += len(t)

    scores = [b["lines"] for b in bins]
    avg_lines = (sum(scores) / len(scores)) if scores else 0

    # 상위 top_ratio 임계값
    sorted_scores = sorted(scores)
    cut_idx = int((1 - top_ratio) * len(sorted_scores))
    cut_idx = max(0, min(cut_idx, len(sorted_scores) - 1))
    threshold = sorted_scores[cut_idx]

    hot = [i for i, sc in enumerate(scores) if sc >= threshold and sc > 0]

    # 인접 bin 병합
    merged = []
    for i in hot:
        if not merged or i > merged[-1][1] + 1:
            merged.append([i, i])
        else:
            merged[-1][1] = i

    # 후보 생성
    candidates = []
    for a, b in merged:
        seg_start = start0 + a * window_sec
        seg_end = start0 + (b + 1) * window_sec

        seg_start2 = max(start0, seg_start - pad_sec)
        seg_end2 = min(end0, seg_end + pad_sec)

        # 후보 구간 내 자막 샘플
        sample = [(s, t) for s, _, t in items if seg_start2 <= s <= seg_end2]
        sample.sort(key=lambda x: x[0])
        sample = sample[:sample_lines]

        lines_sum = sum(bins[i]["lines"] for i in range(a, b + 1))
        chars_sum = sum(bins[i]["chars"] for i in range(a, b + 1))

        # density는 "해당 구간 bin들의 평균 lines" / "전체 평균 lines"
        local_avg = lines_sum / (b - a + 1)
        density = (local_avg / avg_lines) if avg_lines > 0 else 0.0

        candidates.append(
            {
                "start": seg_start2,
                "end": seg_end2,
                "lines": lines_sum,
                "chars": chars_sum,
                "density": density,
                "sample": sample,
            }
        )

    return candidates

def main():
    parser = argparse.ArgumentParser(
        description="Extract high-activity candidate clips from a large SRT (density-based)."
    )
    parser.add_argument("srt_path", help="Path to .srt file (e.g., 1.srt)")
    parser.add_argument("--window", type=int, default=20, help="Bin window seconds (default: 20)")
    parser.add_argument("--top", type=float, default=0.10, help="Top ratio to keep (default: 0.10)")
    parser.add_argument("--pad", type=int, default=40, help="Padding seconds around candidate (default: 40)")
    parser.add_argument("--sample", type=int, default=10, help="Max subtitle lines per candidate (default: 10)")
    parser.add_argument("--out", default="", help="Output file path (optional). If empty, print to stdout.")
    args = parser.parse_args()

    path = Path(args.srt_path)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    items = load_srt(path)
    if not items:
        raise SystemExit("SRT parse failed: check encoding/format (needs 'HH:MM:SS,ms --> ...').")

    candidates = build_candidates(
        items,
        window_sec=args.window,
        top_ratio=args.top,
        pad_sec=args.pad,
        sample_lines=args.sample,
    )

    lines = []
    lines.append("[CANDIDATE_CLIPS]")
    for c in candidates:
        lines.append(
            f"[{format_ts(c['start'])}~{format_ts(c['end'])}] "
            f"lines={c['lines']} chars={c['chars']} density={c['density']:.2f}x"
        )
        for _, t in c["sample"]:
            t2 = t.replace("\n", " ")
            if len(t2) > 80:
                t2 = t2[:80] + "…"
            lines.append(f"- {t2}")
        lines.append("")
    lines.append(f"# 후보 개수: {len(candidates)}")
    output = "\n".join(lines)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Saved: {args.out}")
    else:
        print(output)

if __name__ == "__main__":
    main()