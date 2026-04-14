"""Claude Code CLI 호출 래퍼

긴 프롬프트는 stdin 파이프로 전달하여 명령줄 길이 제한을 회피.
Windows에서 UTF-8 인코딩을 강제하여 한국어 손상을 방지.
"""

import json
import logging
import os
import shutil
import subprocess

from .utils import retry

logger = logging.getLogger("pipeline")


def _check_claude_cli() -> bool:
    """Claude CLI 설치 여부 확인"""
    return shutil.which("claude") is not None


def _log_usage(payload: dict) -> None:
    """Claude CLI JSON 응답의 usage 블록을 구조화된 로그로 남긴다.

    - input_tokens / output_tokens 는 항상 시도
    - cache_creation_input_tokens / cache_read_input_tokens 는 존재할 때만 포함
    - 하나의 토큰 필드도 얻지 못하면 아무 것도 기록하지 않는다 (result/error 경로 보호)
    """
    if not isinstance(payload, dict):
        return
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return

    parts = []
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{key}={int(value)}")
    if not parts:
        return

    extras = []
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id:
        extras.append(f"session_id={session_id}")
    total_cost = payload.get("total_cost_usd")
    if isinstance(total_cost, (int, float)):
        extras.append(f"total_cost_usd={total_cost:.6f}")

    tail = (" " + " ".join(extras)) if extras else ""
    logger.info("Claude usage " + " ".join(parts) + tail)


def _parse_claude_output(result: subprocess.CompletedProcess) -> str:
    """Claude CLI 출력 파싱. JSON 모드와 텍스트 모드 모두 처리."""
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        # stdout 에도 에러 정보가 있을 수 있음
        diag = stderr or stdout or "(stderr/stdout 모두 비어있음)"
        # JSON 출력일 경우 에러 필드 추출
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

    # --output-format json → {"type":"result","result":"...","usage":{...},...}
    # 파싱 실패 시 텍스트 그대로 반환
    try:
        data = json.loads(stdout)

        # 에러 응답 감지 (rate limit, auth 실패 등)
        if isinstance(data, dict):
            if data.get("type") == "error":
                error_msg = data.get("error", data.get("message", "알 수 없는 오류"))
                raise RuntimeError(f"Claude API 오류: {error_msg}")
            if "result" in data:
                _log_usage(data)
                return data["result"]

        # 배열이면 마지막 result 항목
        if isinstance(data, list):
            for item in reversed(data):
                if isinstance(item, dict):
                    if item.get("type") == "error":
                        raise RuntimeError(f"Claude API 오류: {item.get('error', '')}")
                    if item.get("type") == "result":
                        _log_usage(item)
                        return item.get("result", "")

        return stdout
    except json.JSONDecodeError:
        return stdout


@retry(max_retries=2, backoff_base=30.0, exceptions=(RuntimeError, subprocess.TimeoutExpired))
def call_claude(prompt: str, timeout: int = 300) -> str:
    """
    Claude Code CLI를 호출하여 프롬프트 처리.
    stdin 파이프로 프롬프트를 전달하여 명령줄 길이 제한 없이 동작.
    """
    if not _check_claude_cli():
        raise RuntimeError(
            "Claude CLI가 설치되어 있지 않습니다. "
            "https://docs.anthropic.com/en/docs/claude-code 에서 설치하세요."
        )

    logger.debug(f"Claude CLI 호출 ({len(prompt):,}자, timeout={timeout}s)")

    # Windows에서 UTF-8 인코딩 강제 (cp949/cp1252 손상 방지)
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


@retry(max_retries=2, backoff_base=30.0, exceptions=(RuntimeError, subprocess.TimeoutExpired))
def call_claude_with_context(
    prompt: str,
    context: str,
    timeout: int = 300,
) -> str:
    """
    프롬프트와 긴 컨텍스트를 조합하여 Claude에 전달.
    전체를 stdin 파이프로 전달.
    """
    if not _check_claude_cli():
        raise RuntimeError("Claude CLI가 설치되어 있지 않습니다.")

    combined = f"{prompt}\n\n---\n\n{context}"
    logger.debug(f"Claude CLI 호출 (프롬프트 {len(prompt):,}자 + 컨텍스트 {len(context):,}자)")

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    result = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--max-turns", "1"],
        input=combined,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    return _parse_claude_output(result)
