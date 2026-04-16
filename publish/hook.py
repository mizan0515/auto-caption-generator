"""자동 퍼블리시 훅 — VOD 처리 완료 후 site/ 재빌드.

사용 경로:
1. Runtime: pipeline/main.py 의 process_vod() 성공 후 auto_publish_after_vod() 호출.
2. CLI: python -m publish.hook — 수동 재빌드.
3. Python import: from publish.hook import rebuild_site_safe

안전 보장:
- output 파일(md, html, metadata.json) 이 모두 있어야 rebuild 수행.
- rebuild 실패 시 예외를 pipeline 으로 흘리지 않음 (로그만 남김).
- 기존 site/ 가 partial write 로 망가지지 않도록 build_site() 의
  atomic-ish 특성(전체 성공 시에만 index.json 갱신)에 의존.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("publish.hook")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from publish.builder.build_site import build_site  # noqa: E402


def _verify_output_files(output_dir: Path) -> tuple[bool, str]:
    """output 디렉토리에 최소 1세트의 완전한 VOD 산출물이 있는지 검증.

    완전한 세트 = *_metadata.json + 같은 base 의 .md + .html

    Returns:
        (ok, reason) — ok=True 면 rebuild 가능. reason 은 실패 사유.
    """
    if not output_dir.is_dir():
        return False, f"output 디렉토리 없음: {output_dir}"

    meta_files = sorted(output_dir.glob("*_metadata.json"))
    if not meta_files:
        return False, f"metadata.json 파일 없음: {output_dir}"

    complete_count = 0
    for meta_path in meta_files:
        base = meta_path.name[: -len("_metadata.json")]
        md_path = output_dir / f"{base}.md"
        html_path = output_dir / f"{base}.html"
        if md_path.exists() and html_path.exists():
            complete_count += 1

    if complete_count == 0:
        return False, "완전한 VOD 산출물 세트(md+html+metadata) 없음"

    return True, f"완전한 VOD 산출물 {complete_count}세트"


def rebuild_site_safe(
    output_dir: Path | str = "./output",
    site_dir: Path | str = "./site",
    project_root: Path | str | None = None,
) -> dict | None:
    """정적 사이트 빌더를 호출하되, 예외를 파이프라인 런타임으로 흘리지 않는다.

    Safety gates:
    1. output 디렉토리에 완전한 VOD 산출물이 최소 1세트 있어야 함.
    2. build_site() 실패 시 None 반환 (로그만 남김).

    반환:
        성공 시 build_site() 결과 dict. 실패/스킵 시 None.
    """
    try:
        root = Path(project_root) if project_root else _PROJECT_ROOT
        out = Path(output_dir).resolve()

        # Safety gate: output 검증
        ok, reason = _verify_output_files(out)
        if not ok:
            logger.warning(f"publish rebuild 스킵: {reason}")
            return None

        result = build_site(
            output_dir=out,
            site_dir=Path(site_dir).resolve(),
            project_root=root,
        )
        logger.info(
            f"✓ publish rebuild 완료: "
            f"{result['vod_count']} VODs, {result['streamer_count']} streamers"
        )
        return result
    except Exception as e:  # noqa: BLE001
        logger.warning(f"publish rebuild 실패 (무시): {e}")
        return None


def auto_publish_after_vod(
    cfg: dict,
    result_md: Optional[str],
    result_html: Optional[str],
    result_meta: Optional[str],
    logger_override=None,
) -> dict | None:
    """VOD 처리 성공 후 호출되는 자동 퍼블리시 진입점.

    Args:
        cfg: pipeline config dict
        result_md: 생성된 md 파일 경로
        result_html: 생성된 html 파일 경로
        result_meta: 생성된 metadata json 파일 경로
        logger_override: 로거 오버라이드 (없으면 모듈 로거 사용)

    Returns:
        성공 시 build_site() 결과 dict. 스킵/실패 시 None.
    """
    log = logger_override or logger

    # Gate 1: autorebuild 활성화 여부
    if not cfg.get("publish_autorebuild", False):
        log.debug("publish_autorebuild=false — 자동 퍼블리시 스킵")
        return None

    # Gate 2: 이번 VOD 의 산출물이 모두 있는지
    for label, path in [("md", result_md), ("html", result_html), ("metadata", result_meta)]:
        if not path or not os.path.exists(path):
            log.warning(f"publish 스킵: {label} 파일 없음 — {path}")
            return None

    # Gate 3: output 디렉토리 전체 검증 + rebuild
    output_dir = cfg.get("output_dir", "./output")
    site_dir = cfg.get("publish_site_dir", "./site")

    log.info("자동 퍼블리시 site rebuild 시작...")
    result = rebuild_site_safe(
        output_dir=output_dir,
        site_dir=site_dir,
    )

    if result is None:
        log.warning("자동 퍼블리시 실패 또는 스킵")
    else:
        log.info(
            f"✓ 자동 퍼블리시 완료: site_dir={result['site_dir']}, "
            f"vods={result['vod_count']}, streamers={result['streamer_count']}"
        )

    return result


def main() -> int:
    result = rebuild_site_safe()
    if result is None:
        return 1
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["vod_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
