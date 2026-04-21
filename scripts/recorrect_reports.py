"""기존 output/*.md 리포트의 고유명사/맥락 오인식을 사후 교정.

동작:
1. output/ 의 각 .md + metadata.json 쌍을 돌며, 해당 VOD 의 work_dir 에서 채팅/커뮤니티 로드.
2. 스트리머별 lexicon 을 빌드 (pipeline.lexicon).
3. Claude 에게 lexicon + 채팅 상위 어휘 + 커뮤니티 표기 + 기존 md 를 주고 "자막 오인식만 최소 개입으로 교정" 지시.
4. 돌려받은 교정본으로 md 덮어쓰기 (원본은 .md.bak 백업).
5. 교정된 VOD 가 1개 이상이면 scripts.refresh_reports 의 publish 훅을 호출해 html 재렌더 + 배포.

안전 장치:
- --dry-run: 교정 diff 만 로그, 실제 쓰기는 하지 않는다.
- --video-no N : 특정 VOD 만 교정.
- 교정본이 원본의 80% 미만 길이면 Claude 가 내용을 자의적으로 줄였다는 뜻 → 거부.
- 교정 전후 taxonomy (## 헤딩 개수) 가 달라지면 거부.

사용:
    python -m scripts.recorrect_reports                 # 전체
    python -m scripts.recorrect_reports --video-no 12784380
    python -m scripts.recorrect_reports --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import load_config  # noqa: E402
from pipeline.lexicon import build_lexicon  # noqa: E402


def _call_claude_text(system_prompt: str, user_prompt: str, timeout: int = 600,
                      max_retries: int = 3) -> str:
    """Claude CLI 호출 (text 출력 모드) + 지수 백오프 재시도.

    JSON 모드는 긴 verbatim 마크다운을 주면 result=""로 돌려주는 재현 가능한 버그가
    있어 (num_turns=1, end_turn, output_tokens 수천), 여기서는 --output-format text
    를 사용한다. 사용량 메트릭은 포기하지만 본문을 안정적으로 회수할 수 있다.

    rate-limit (code=1, stderr 빈 상태의 즉시 실패) 는 지수 백오프로 재시도.
    """
    import os as _os
    import subprocess
    import time as _time
    combined = f"{system_prompt}\n\n---\n\n{user_prompt}" if system_prompt else user_prompt
    cmd = ["claude", "-p", "--output-format", "text", "--max-turns", "1"]
    cflags = 0
    if sys.platform == "win32":
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    last_err = ""
    for attempt in range(max_retries):
        if attempt > 0:
            wait = min(60, 5 * (2 ** (attempt - 1)))
            logger.info(f"  Claude CLI 재시도 {attempt}/{max_retries - 1} ({wait}s 대기)")
            _time.sleep(wait)
        result = subprocess.run(
            cmd, input=combined, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            env={**_os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=cflags,
        )
        if result.returncode == 0 and (result.stdout or "").strip():
            return result.stdout
        last_err = (result.stderr or result.stdout or "(no output)").strip()[:500]
        logger.warning(f"  Claude CLI 실패 (code={result.returncode}, try={attempt + 1}): {last_err}")
    raise RuntimeError(f"Claude CLI 재시도 모두 실패: {last_err}")

logger = logging.getLogger("scripts.recorrect_reports")

SYSTEM_PROMPT = """너는 한국 라이브 방송 요약 리포트의 교정자다.
입력 MD 는 Whisper 자막 기반 Claude 요약이며, 고유명사/신조어/별명/게임 용어가 자주 잘못 표기된다.
네 임무는 **자막 오인식에서 비롯된 고유명사 표기 오류만** 식별해 교정 매핑을 출력하는 것.

## 교정 원칙
1. 주입된 `알려진 고유명사` + `채팅 빈출 표기` + `커뮤니티 표기` 를 정답 사전으로 간주한다.
2. MD 안의 이름·별명·밈·게임 용어 중 사전과 발음이 유사한데 표기가 다른 것만 사전 표기로 매핑한다.
3. 일반 명사·동사·서술어는 절대 매핑 금지. 오직 사람 이름·캐릭터·게임 용어·고유명사만.
4. 확신이 없으면 매핑하지 말 것. 추측 금지.
5. 한 매핑 (`old → new`) 는 MD 전체에 적용되니, 양쪽이 모두 정확한 표기인지 확인할 것.

## 출력 형식 (반드시 이 JSON 만)
```json
{"replacements": [{"old": "삐구", "new": "삐부"}, {"old": "따윤희", "new": "따효니"}]}
```
- 다른 텍스트 금지. 코드펜스 ```json 감쌈은 허용.
- 교정할 게 없으면 `{"replacements": []}`.
- old 와 new 는 정확히 같은 글자 수일 필요는 없지만 짧은 토큰 (보통 2-8자) 이어야 함.
- old 가 MD 에 실제로 존재하는 문자열이어야 함 (substring 매치).
"""


def _iter_report_pairs(output_dir: Path):
    for meta in sorted(output_dir.glob("*_metadata.json")):
        base = meta.name[: -len("_metadata.json")]
        md = output_dir / f"{base}.md"
        if md.is_file():
            yield base, md, meta


def _load_metadata(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"metadata 읽기 실패 {meta_path}: {e}")
        return {}


def _top_chat_tokens(chat_path: Path, limit: int = 40) -> list[str]:
    if not chat_path.is_file():
        return []
    try:
        rows = json.loads(chat_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cnt: Counter = Counter()
    rx = re.compile(r"[A-Za-z가-힣][A-Za-z0-9가-힣]{1,}")
    for r in rows or []:
        for t in rx.findall((r.get("msg") or "") if isinstance(r, dict) else ""):
            if 2 <= len(t) <= 20:
                cnt[t] += 1
    return [t for t, _ in cnt.most_common(limit)]


def _community_terms(posts_path: Path, limit: int = 40) -> list[str]:
    if not posts_path.is_file():
        return []
    try:
        posts = json.loads(posts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cnt: Counter = Counter()
    rx = re.compile(r"[A-Za-z가-힣][A-Za-z0-9가-힣]{1,}")
    for p in posts or []:
        if not isinstance(p, dict):
            continue
        for field in ("title", "body_preview"):
            for t in rx.findall(p.get(field) or ""):
                if 2 <= len(t) <= 20:
                    cnt[t] += 1
    return [t for t, _ in cnt.most_common(limit)]


def _build_user_prompt(md_text: str, lexicon: list[str],
                       chat_tokens: list[str], community: list[str],
                       title: str) -> str:
    return f"""VOD 제목: {title}

## 알려진 고유명사 (사전)
{', '.join(lexicon) if lexicon else '(비어 있음)'}

## 채팅 빈출 표기 (사용자 원문)
{', '.join(chat_tokens) if chat_tokens else '(비어 있음)'}

## 커뮤니티 빈출 표기
{', '.join(community) if community else '(비어 있음)'}

## 원본 MD (교정 대상)
{md_text}
"""


_HEADING_RE = re.compile(r"^#{1,6}\s", re.M)


def _parse_replacements(raw: str) -> list[tuple[str, str]]:
    """Claude 응답에서 replacements 리스트 추출.

    응답 예시:
        ```json
        {"replacements": [{"old": "삐구", "new": "삐부"}, ...]}
        ```
    코드펜스 / 주변 텍스트 / trailing comma 등에 강건하게 동작.
    """
    s = (raw or "").strip()
    if not s:
        return []
    # 코드펜스 제거
    if s.startswith("```"):
        s = s.strip("`").strip()
        nl = s.find("\n")
        if nl > 0 and s[:nl].strip().lower() in ("json", ""):
            s = s[nl + 1:]
    # 본문 안에서 첫 번째 `{` 부터 마지막 `}` 까지만 잘라낸다.
    lo, hi = s.find("{"), s.rfind("}")
    if lo < 0 or hi <= lo:
        return []
    blob = s[lo:hi + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    items = data.get("replacements") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[tuple[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        old = it.get("old")
        new = it.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            continue
        old = old.strip()
        new = new.strip()
        if not old or old == new:
            continue
        # 안전성: 너무 짧거나 너무 긴 토큰 거부
        if not (1 <= len(old) <= 30) or not (1 <= len(new) <= 30):
            continue
        out.append((old, new))
    return out


def _apply_replacements(text: str, repls: list[tuple[str, str]]) -> tuple[str, list[tuple[str, str, int]]]:
    """순서대로 replace 적용. 반환: (새 텍스트, [(old, new, count)])"""
    applied: list[tuple[str, str, int]] = []
    cur = text
    for old, new in repls:
        # old 가 new 의 부분문자열이면 무한 치환 위험은 없지만 (replace 는 1패스),
        # new 가 old 를 포함하면 다음 매핑에서 다시 잡힐 수 있어 순서가 중요.
        cnt = cur.count(old)
        if cnt == 0:
            applied.append((old, new, 0))
            continue
        cur = cur.replace(old, new)
        applied.append((old, new, cnt))
    return cur, applied


def _sanity_check(original: str, corrected: str) -> tuple[bool, str]:
    if not corrected.strip():
        return False, "교정본이 비어있음"
    if len(corrected) < len(original) * 0.8:
        return False, f"교정본 길이 급감 ({len(corrected)} < {len(original)}*0.8)"
    if len(corrected) > len(original) * 1.3:
        return False, f"교정본 길이 급증 ({len(corrected)} > {len(original)}*1.3)"
    orig_h = len(_HEADING_RE.findall(original))
    corr_h = len(_HEADING_RE.findall(corrected))
    if orig_h != corr_h:
        return False, f"헤딩 수 변경 {orig_h}→{corr_h}"
    # 타임스탬프 개수 동일해야 함
    ts_re = re.compile(r"\d{2}:\d{2}:\d{2}")
    if len(ts_re.findall(original)) != len(ts_re.findall(corrected)):
        return False, "타임스탬프 개수 변경"
    return True, "ok"


def _diff_summary(a: str, b: str, max_lines: int = 10) -> str:
    import difflib
    diff = list(difflib.unified_diff(
        a.splitlines(), b.splitlines(), lineterm="", n=0,
    ))
    diff = [d for d in diff if d.startswith(("+", "-")) and not d.startswith(("+++", "---"))]
    head = diff[: max_lines * 2]
    more = "" if len(diff) <= max_lines * 2 else f"  ... ({len(diff) - max_lines * 2} more)"
    return "\n".join(head) + ("\n" + more if more else "")


def recorrect_one(md_path: Path, meta: dict, cfg: dict, dry_run: bool) -> tuple[bool, str]:
    video_no = str(meta.get("video_no") or "")
    title = meta.get("title") or ""
    channel_id = meta.get("channel_id") or ""
    channel_name = meta.get("channel") or ""
    work_dir = Path(cfg.get("work_dir", "./work")) / video_no

    original = md_path.read_text(encoding="utf-8")

    lexicon = build_lexicon(
        channel_id=channel_id,
        channel_name=channel_name,
        video_no=video_no,
        vod_title=title,
        work_dir=cfg.get("work_dir", "./work"),
        limit=int(cfg.get("lexicon_limit", 30)),
        fetch_namuwiki=False,
        cache_ttl_sec=int(cfg.get("lexicon_cache_ttl_hours", 168)) * 3600,
    )
    chat_tokens = _top_chat_tokens(work_dir / f"{video_no}_chat.log.json")
    community = _community_terms(work_dir / f"{video_no}_community.json")

    if not (lexicon or chat_tokens or community):
        return False, "사전 없음 — 스킵"

    user_prompt = _build_user_prompt(original, lexicon, chat_tokens, community, title)
    logger.info(f"  [{video_no}] Claude 교정 매핑 요청 ({len(original):,}자, lexicon={len(lexicon)})")
    try:
        raw = _call_claude_text(
            SYSTEM_PROMPT, user_prompt,
            timeout=int(cfg.get("claude_timeout", 600)),
        )
    except Exception as e:  # noqa: BLE001
        return False, f"Claude 호출 실패: {e}"

    repls = _parse_replacements(raw)
    if not repls:
        return False, "변경 없음"

    corrected, applied = _apply_replacements(original, repls)
    effective = [(o, n, c) for (o, n, c) in applied if c > 0]
    if not effective:
        # Claude 가 매핑은 줬지만 MD 에서 매치 0 → 잘못된 추측
        logger.info(f"  [{video_no}] 매핑 {len(repls)}개 모두 매치 0 → 무시")
        return False, "변경 없음 (매치 0)"

    if corrected == original:
        return False, "변경 없음"

    ok, why = _sanity_check(original, corrected)
    if not ok:
        logger.warning(f"  [{video_no}] sanity 실패: {why} — 원본 유지")
        return False, f"reject: {why}"

    summary = ", ".join(f"'{o}'→'{n}'×{c}" for o, n, c in effective)
    logger.info(f"  [{video_no}] 적용 매핑: {summary}")

    if dry_run:
        return True, "dry-run"

    # 백업 후 덮어쓰기
    bak = md_path.with_suffix(md_path.suffix + ".bak")
    if not bak.exists():
        bak.write_text(original, encoding="utf-8")
    md_path.write_text(corrected, encoding="utf-8")

    # 메트릭: 어떤 매핑이 적용됐는지 사이드카에 누적 기록.
    # 분석/튜닝용 — lexicon 품질 개선에 어떤 후보가 효과적이었는지 추적.
    try:
        _record_metric(md_path, video_no, lexicon, effective)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"  [{video_no}] 메트릭 기록 실패 (무시): {e}")

    return True, "patched"


def _record_metric(md_path: Path, video_no: str,
                   lexicon: list[str], applied: list[tuple[str, str, int]]) -> None:
    """`output/recorrect_metrics.json` 에 적용 매핑 누적.

    형식:
        {"runs": [
            {"ts": "...", "video_no": "...", "applied": [["old","new",count], ...],
             "lexicon_hit": ["new1", "new2"]}
        ]}

    lexicon_hit: 매핑의 new 가 이번 lexicon 안에 있던 경우 — lexicon 의 진짜 효용 측정.
    """
    import datetime as _dt
    metrics_path = md_path.parent / "recorrect_metrics.json"
    payload = {"runs": []}
    if metrics_path.exists():
        try:
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
                payload = {"runs": []}
        except (OSError, json.JSONDecodeError):
            payload = {"runs": []}
    lex_set = set(lexicon)
    payload["runs"].append({
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "video_no": video_no,
        "applied": [[o, n, c] for (o, n, c) in applied],
        "lexicon_hit": sorted({n for (_, n, _) in applied if n in lex_set}),
    })
    # 무한 누적 방지: 최근 200건만 유지
    payload["runs"] = payload["runs"][-200:]
    metrics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--video-no", default=None, help="특정 VOD 만 교정")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--no-publish", action="store_true",
                    help="교정 완료 후 refresh_reports 퍼블리시 훅 건너뜀")
    ap.add_argument("--rebuild-lexicon", action="store_true",
                    help="lexicon 캐시 강제 무효화 후 재빌드 (신조어/표기 갱신용)")
    ap.add_argument("--force", action="store_true",
                    help="이미 교정된 VOD (.md.bak 존재 + .md mtime ≤ .bak mtime) 도 다시 호출")
    args = ap.parse_args()

    cfg = load_config()
    if args.rebuild_lexicon:
        # ttl=0 → build_lexicon 이 매번 재계산
        cfg = {**cfg, "lexicon_cache_ttl_hours": 0}
        logger.info("lexicon 캐시 무효화 모드 (ttl=0)")
    out_dir = Path(args.output_dir or cfg.get("output_dir", "./output"))
    if not out_dir.is_dir():
        logger.error(f"output 디렉토리 없음: {out_dir}")
        return 2

    changed = 0
    total = 0
    skipped = 0
    # Lexicon 갱신 시(--rebuild-lexicon) 또는 --force 시에는 모든 VOD 재호출.
    # 그 외: .bak 가 이미 있으면 한 번 교정된 적 있으니 스킵 (재실행 비용 절감).
    skip_patched = not (args.force or args.rebuild_lexicon)
    for base, md_path, meta_path in _iter_report_pairs(out_dir):
        meta = _load_metadata(meta_path)
        vn = str(meta.get("video_no") or "")
        if args.video_no and vn != str(args.video_no):
            continue
        total += 1
        bak = md_path.with_suffix(md_path.suffix + ".bak")
        if skip_patched and bak.exists():
            skipped += 1
            logger.info(f"  [{vn}] 이미 교정됨 (--force 로 재호출 가능)")
            continue
        try:
            ok, status = recorrect_one(md_path, meta, cfg, args.dry_run)
        except Exception as e:  # noqa: BLE001
            logger.error(f"  [{vn}] 예외: {e}")
            continue
        logger.info(f"  [{vn}] {status}")
        if ok:
            changed += 1

    logger.info(f"총 {changed}/{total} 개 교정됨 (skip {skipped})")

    # 교정된 내용이 있으면 refresh_reports 를 통해 html 재렌더 + 배포.
    if changed > 0 and not args.dry_run and not args.no_publish:
        logger.info("refresh_reports 호출 (html 재렌더 + 퍼블리시) ...")
        import runpy
        sys.argv = ["scripts.refresh_reports"]
        try:
            runpy.run_module("scripts.refresh_reports", run_name="__main__")
        except SystemExit as e:
            return int(e.code or 0)

    return 0


if __name__ == "__main__":
    sys.exit(main())
