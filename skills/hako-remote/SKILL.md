---
name: hako-remote
description: "Execute commands on remote HAKO workers, poll for results, and manage worker fleet. Use when asked to: run commands on devbox/remote worker, build Edge, check worker status, execute shell on remote machines."
---

# HAKO Remote Execution Skill

Submit commands to remote HAKO workers via gRPC and poll until completion.

## Prerequisites

- HAKO client with venv at `~/workspace/HAKO/client/.venv/`
- Config at `~/.hako_client/config.json` with `server_url`
- Authenticated (`auth_state.json` with valid session token)

## Script

`scripts/hako-run.py` — universal CLI for HAKO worker operations.

### Usage

```bash
PYTHON=~/workspace/HAKO/client/.venv/bin/python
SCRIPT=<skill_dir>/scripts/hako-run.py

# List online workers
$PYTHON $SCRIPT --list

# Run command on a worker (auto-polls until done)
$PYTHON $SCRIPT <worker_id> --cwd <dir> <command...>

# Query a task
$PYTHON $SCRIPT --query <task_id> <worker_id>

# With default worker (set HAKO_DEFAULT_WORKER env)
$PYTHON $SCRIPT --cwd Q:\Edge\src git log --oneline -5
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--list` | | List online workers |
| `--query TASK_ID` | | Query task result |
| `--cwd DIR` | worker project_root | Working directory on remote |
| `--timeout SECS` | 3600 | Task timeout in seconds |
| `--poll SECS` | 5 | Poll interval in seconds |

### Examples

```bash
# Check worker fleet
$PYTHON $SCRIPT --list

# Run git command on devbox
$PYTHON $SCRIPT e522... --cwd Q:\Edge\src git pull origin main

# Build Edge (long timeout)
$PYTHON $SCRIPT e522... --cwd Q:\Edge\src --timeout 7200 cmd /c "autoninja -C out\win_x64_debug_developer_build chrome"

# Check a running task
$PYTHON $SCRIPT --query abc123-task-id e522...
```

## Known Workers

| Alias | Host | Worker ID (prefix) | Project |
|-------|------|-------------------|---------|
| devbox | CPC-zhui-AT02S6 | e52287dc... | Q:\Edge |

## Notes

- All shell commands on HAKO workers run async — the script submits then polls
- For long tasks (build, sync), use `--timeout 7200` (2 hours)
- Edge repo `git fetch/pull` can take 5-15 minutes due to repo size
- Output is truncated to last 100 lines; full output is in worker's data_dir
