# B30 state and daemon guard

## Goal

Stabilize basic-mode execution by preventing:

- duplicate daemon instances from running concurrently
- a stale worker from overwriting an already completed VOD back to a non-terminal status

## Changes

- Added a process-wide daemon lock in `pipeline/main.py`
- Added the same single-instance guard to dashboard-owned daemon startup in `pipeline/daemon.py`
- Added a terminal-state regression guard in `pipeline/state.py`

## Verification

- `python experiments/b30_state_and_daemon_guard.py`
- `python -c "from pipeline.main import _acquire_daemon_lock; from pipeline.state import PipelineState; print('ok')"`

## Result

- PASS: second daemon instance is refused while the first lock is held
- PASS: a VOD already marked `completed` no longer regresses back to `summarizing`
