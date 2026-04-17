"""Claude API 호출 래퍼 — Anthropic SDK 직접 호출 (프롬프트 캐싱 지원)

우선순위:
  1. Anthropic SDK (anthropic 패키지 + ANTHROPIC_API_KEY) → 프롬프트 캐싱 활용
  2. Claude Code CLI (claude -p) → fallback

프롬프트 캐싱:
  call_claude_cached() 는 system 프롬프트에 cache_control 을 설정하여
  동일 system 프롬프트를 반복 호출할 때 input token 비용을 ~90% 절감한다.
  이전 구조(매 청크마다 subprocess)에서는 프롬프트 캐싱이 불가능했다.
"""

import json
import logging
import os
import shutil
import subprocess
from typing import Optional

from .utils import retry

logger = logging.getLogger("pipeline")

# ── Anthropic SDK (1순위) ──────────────────────────────────────

_anthropic_client = None
_sdk_available: Optional[bool] = None


def _check_sdk() -> bool:
    """Anthropic SDK 사용 가능 여부 (패키지 + API 키)"""
    global _sdk_available
    if _sdk_available is not None:
        return _sdk_available
    try:
        import anthropic  # noqa: F401
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        _sdk_available = bool(key)
        if not _sdk_available:
            logger.info("ANTHROPIC_API_KEY 미설정 → Claude CLI fallback 사용")
        else:
            logger.info("Anthropic SDK 사용 (프롬프트 캐싱 활성)")
    except ImportError:
        _sdk_available = False
        logger.info("anthropic 패키지 미설치 → Claude CLI fallback 사용")
    return _sdk_available


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def _log_api_usage(usage, model: str = "") -> None:
    """Anthropic SDK 응답의 usage 객체를 로깅."""
    parts = []
    for attr in ("input_tokens", "output_tokens",
                 "cache_creation_input_tokens", "cache_read_input_tokens"):
        val = getattr(usage, attr, None)
        if isinstance(val, (int, float)) and val > 0:
            parts.append(f"{attr}={int(val)}")
    if parts:
        logger.info(f"Claude API usage ({model}) " + " ".join(parts))


@retry(max_retries=2, backoff_base=30.0, exceptions=(RuntimeError,))
def call_claude_cached(
    user_prompt: str,
    system_prompt: str = "",
    timeout: int = 300,
    model: str = "",
) -> str:
    """Anthropic SDK로 호출. system_prompt에 프롬프트 캐싱 적용.

    - system_prompt: 캐싱할 시스템 지시문 (청크간 공유되는 불변 부분)
    - user_prompt: 매 호출마다 달라지는 데이터 (자막, 채팅 등)
    - model: 빈 문자열이면 pipeline_config 의 claude_model 사용

    SDK가 사용 불가능하면 자동으로 CLI fallback.
    """
    if not model:
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    if not _check_sdk():
        # CLI fallback: system + user 를 하나로 합쳐서 전달
        combined = f"{system_prompt}\n\n---\n\n{user_prompt}" if system_prompt else user_prompt
        return _call_claude_cli(combined, timeout=timeout)

    client = _get_client()

    system_blocks = []
    if system_prompt:
        system_blocks = [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]

    logger.debug(
        f"Claude API 호출 (model={model}, "
        f"system={len(system_prompt):,}자, user={len(user_prompt):,}자)"
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=system_blocks if system_blocks else [],
            messages=[{"role": "user", "content": user_prompt}],
            timeout=timeout,
        )
    except Exception as e:
        error_str = str(e)
        # 인증/과금 오류는 재시도 무의미
        if any(k in error_str.lower() for k in ("authentication", "unauthorized", "invalid api key")):
            logger.error(f"API 인증 실패: {error_str[:300]}")
            raise RuntimeError(f"Anthropic API 인증 실패: {error_str[:300]}")
        # rate limit 등은 retry 데코레이터가 처리
        raise RuntimeError(f"Anthropic API 오류: {error_str[:500]}")

    _log_api_usage(response.usage, model)

    # 텍스트 블록 추출
    text_parts = []
    for block in response.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
    result = "\n".join(text_parts)
    if not result:
        raise RuntimeError("Claude API가 빈 응답을 반환했습니다.")
    return result


# ── Claude Code CLI (fallback) ─────────────────────────────────

def _check_claude_cli() -> bool:
    """Claude CLI 설치 여부 확인"""
    return shutil.which("claude") is not None


def _log_cli_usage(payload: dict) -> None:
    """Claude CLI JSON 응답의 usage 블록을 구조화된 로그로 남긴다."""
    if not isinstance(payload, dict):
        return
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return

    parts = []
    for key in (
        "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{key}={int(value)}")
    if not parts:
        return

    extras = []
    total_cost = payload.get("total_cost_usd")
    if isinstance(total_cost, (int, float)):
        extras.append(f"total_cost_usd={total_cost:.6f}")

    tail = (" " + " ".join(extras)) if extras else ""
    logger.info("Claude CLI usage " + " ".join(parts) + tail)


def _parse_claude_output(result: subprocess.CompletedProcess) -> str:
    """Claude CLI 출력 파싱. JSON 모드와 텍스트 모드 모두 처리."""
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        diag = stderr or stdout or "(stderr/stdout 모두 비어있음)"
        if stdout:
            try:
                data = json.loads(stdout)
                if isinstance(data, dict) and (data.get("type") == "error" or "error" in data):
                    diag = f"{data.get('error', data.get('message', diag))}"
            except (json.JSONDecodeError, TypeError):
                pass
        logger.error(f"Claude CLI stderr: {stderr[:500]}")
        logger.error(f"Claude CLI stdout: {stdout[:500]}")
        raise RuntimeError(f"Claude CLI 실패 (code={result.returncode}): {diag[:500]}")

    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError("Claude CLI가 빈 응답을 반환했습니다.")

    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            if data.get("type") == "error":
                error_msg = data.get("error", data.get("message", "알 수 없는 오류"))
                raise RuntimeError(f"Claude API 오류: {error_msg}")
            if "result" in data:
                _log_cli_usage(data)
                return data["result"]
        if isinstance(data, list):
            for item in reversed(data):
                if isinstance(item, dict):
                    if item.get("type") == "error":
                        raise RuntimeError(f"Claude API 오류: {item.get('error', '')}")
                    if item.get("type") == "result":
                        _log_cli_usage(item)
                        return item.get("result", "")
        return stdout
    except json.JSONDecodeError:
        return stdout


@retry(max_retries=2, backoff_base=30.0, exceptions=(RuntimeError, subprocess.TimeoutExpired))
def _call_claude_cli(prompt: str, timeout: int = 300) -> str:
    """Claude Code CLI를 호출 (fallback 경로)."""
    if not _check_claude_cli():
        raise RuntimeError(
            "Claude CLI가 설치되어 있지 않습니다. "
            "https://docs.anthropic.com/en/docs/claude-code 에서 설치하세요."
        )

    logger.debug(f"Claude CLI 호출 ({len(prompt):,}자, timeout={timeout}s)")

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    result = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--max-turns", "1"],
        input=prompt,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    return _parse_claude_output(result)


# ── 하위 호환 API ──────────────────────────────────────────────

def call_claude(prompt: str, timeout: int = 300) -> str:
    """기존 인터페이스 호환. SDK 가능하면 SDK, 아니면 CLI."""
    return call_claude_cached(user_prompt=prompt, timeout=timeout)


def call_claude_with_context(prompt: str, context: str, timeout: int = 300) -> str:
    """기존 인터페이스 호환."""
    combined = f"{prompt}\n\n---\n\n{context}"
    return call_claude_cached(user_prompt=combined, timeout=timeout)
