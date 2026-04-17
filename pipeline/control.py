"""트레이 프로세스 ↔ 대시보드 간 제어 명령 파일 IPC.

왜 이 파일이 있는가:
- MS Store Python / Windows 11 환경에서 Shell_NotifyIcon 이 샌드박스나
  설정 때문에 트레이 아이콘이 실제로 표시되지 않는 경우가 있다. 이 경우
  트레이 메뉴로는 파이프라인을 제어할 수 없다.
- 대시보드(별도 프로세스)는 무조건 보이는 창이라서 거기서 일시정지/재개/종료
  명령을 내릴 수 있어야 한다. 파일 기반 IPC 로 간단히 해결.

프로토콜:
- 대시보드가 `output/pipeline.control.json` 에 {"action": "...", "ts": N,
  "token": N} 을 쓴다.
- 트레이가 주기적으로 읽어 token 이 바뀌었으면 1회 실행. token 은 단조 증가.
- 실행 후 트레이가 `output/pipeline.control.ack.json` 에 동일 token 을 기록.
- 실패/미전파는 그대로 둔다 — stateless best-effort.

지원 액션: "pause", "resume", "quit".
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONTROL_FILENAME = "pipeline.control.json"
ACK_FILENAME = "pipeline.control.ack.json"
VALID_ACTIONS = ("pause", "resume", "quit")


@dataclass
class ControlCommand:
    action: str
    token: int
    ts: float


def control_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / CONTROL_FILENAME


def ack_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / ACK_FILENAME


def write_command(output_dir: str | Path, action: str) -> int:
    """대시보드에서 호출. 다음 token 을 할당해 명령 파일에 쓴다.

    Returns: 쓰인 token (비동기 확인용). 액션이 잘못되면 ValueError.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"지원하지 않는 액션: {action}")
    path = control_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 기존 token 읽기 (없거나 파싱 실패면 0)
    prev = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            prev = int(json.load(f).get("token", 0))
    except (OSError, ValueError, TypeError):
        prev = 0
    new_token = prev + 1

    payload = {"action": action, "token": new_token, "ts": time.time()}
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)
    return new_token


def read_command(output_dir: str | Path) -> Optional[ControlCommand]:
    """트레이 / 데몬에서 호출. 현재 명령 파일을 읽어 반환 (미존재 시 None)."""
    path = control_path(output_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        action = data.get("action")
        token = int(data.get("token", 0))
        ts = float(data.get("ts", 0.0))
        if action not in VALID_ACTIONS or token <= 0:
            return None
        return ControlCommand(action=action, token=token, ts=ts)
    except (OSError, ValueError, TypeError):
        return None


def write_ack(output_dir: str | Path, token: int, action: str) -> None:
    """트레이가 명령 처리 후 호출. 대시보드가 확인할 수 있게 ack 기록."""
    path = ack_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"token": token, "action": action, "ts": time.time()}
    tmp = path.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def read_ack(output_dir: str | Path) -> Optional[dict]:
    path = ack_path(output_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
