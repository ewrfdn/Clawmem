#!/usr/bin/env python3
"""hako-run: Submit a command to a HAKO worker and poll until completion.

Usage:
    hako-run <worker_id> <command...>
    hako-run <worker_id> --cwd <dir> <command...>
    hako-run --list                          # list workers
    hako-run --query <task_id> [worker_id]   # query a task

Examples:
    hako-run e522... git log --oneline -5
    hako-run e522... --cwd Q:\\Edge\\src git pull origin main
    hako-run e522... cmd /c "gclient sync -D -f && autoninja -C out\\dir chrome"
    hako-run --list
    hako-run --query abc123-task-id e522...

Environment:
    HAKO_DEFAULT_WORKER  - default worker ID if not specified
"""

import asyncio
import sys
import os
import time
import argparse

# Add client to path - try multiple locations
_script_dir = os.path.dirname(os.path.abspath(__file__))
for _candidate in [
    os.path.join(_script_dir, 'HAKO', 'client'),
    os.path.join(_script_dir, '..', 'HAKO', 'client'),
    os.path.join(os.path.expanduser('~'), 'workspace', 'HAKO', 'client'),
]:
    if os.path.isfile(os.path.join(_candidate, 'config.py')):
        sys.path.insert(0, _candidate)
        break

from config import HakoConfig
from grpc_client import init_client_auth, submit_task, get_task_result, list_workers, close
from generated import worker_pb2

STATUS_NAMES = {0: 'pending', 1: 'running', 2: 'success', 3: 'failed', 4: 'cancelled'}
POLL_INTERVAL = 5  # seconds


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


async def do_list():
    config = HakoConfig.load()
    await init_client_auth(config)
    resp = await list_workers()
    if not resp.workers:
        print("No workers online")
    else:
        print(f"{'ID':<20} {'Host':<25} {'OS':<10} {'Status':<10} {'Project'}")
        print("-" * 100)
        for w in resp.workers:
            s = STATUS_NAMES.get(w.status, '?')
            short_id = w.id[:16] + '...'
            print(f"{short_id:<20} {w.hostname:<25} {w.os:<10} {s:<10} {w.project_root}")
    await close()


async def do_query(task_id: str, worker_id: str):
    config = HakoConfig.load()
    await init_client_auth(config)
    r = await get_task_result(task_id=task_id, worker_id=worker_id)
    s = STATUS_NAMES.get(r.status, f'unknown({r.status})')
    print(f"Status: {s}")
    if r.result.output:
        print(r.result.output)
    if r.result.error:
        print(f"Error: {r.result.error}")
    await close()


async def do_run(worker_id: str, args: list[str], cwd: str, timeout: float):
    config = HakoConfig.load()
    await init_client_auth(config)

    print(f"Worker:  {worker_id[:16]}...")
    print(f"CWD:     {cwd}")
    print(f"Command: {' '.join(args)}")
    print(f"Timeout: {format_duration(timeout)}")
    print("-" * 60)

    resp = await submit_task(
        worker_id=worker_id,
        task_type=worker_pb2.TASK_TYPE_SYNC,
        timeout=timeout,
        shell=worker_pb2.ShellOperation(args=args, working_dir=cwd),
    )

    # Extract task_id
    task_id = ''
    if resp.result.output and 'task_id:' in resp.result.output:
        for line in resp.result.output.splitlines():
            if line.startswith('task_id:'):
                task_id = line.split(':', 1)[1].strip()
                break

    if not task_id:
        # Direct result (not async)
        if resp.result.output:
            print(resp.result.output)
        if resp.result.error:
            print(f"Error: {resp.result.error}")
        await close()
        sys.exit(0 if resp.result.success else 1)

    # Poll
    print(f"Task:    {task_id}")
    print(f"Polling every {POLL_INTERVAL}s...")
    print()

    start = time.time()
    last_status = ''
    while True:
        try:
            r = await get_task_result(task_id=task_id, worker_id=worker_id)
        except Exception as e:
            elapsed = format_duration(time.time() - start)
            print(f"  [{elapsed}] Poll error: {e}, retrying...")
            await asyncio.sleep(POLL_INTERVAL)
            continue

        s = STATUS_NAMES.get(r.status, f'unknown({r.status})')
        elapsed = format_duration(time.time() - start)

        if s != last_status:
            print(f"  [{elapsed}] Status: {s}")
            last_status = s

        if r.status in (2, 3, 4):
            # Done
            print(f"\n{'=' * 60}")
            print(f"Result: {s.upper()} ({elapsed})")
            print(f"{'=' * 60}")
            if r.result.output:
                # Print output, limit to last 100 lines if huge
                lines = r.result.output.strip().splitlines()
                if len(lines) > 100:
                    print(f"... ({len(lines) - 100} lines omitted)")
                    lines = lines[-100:]
                for l in lines:
                    print(l)
            if r.result.error:
                print(f"\nError:\n{r.result.error}")
            await close()
            sys.exit(0 if r.status == 2 else 1)

        await asyncio.sleep(POLL_INTERVAL)


def main():
    # Manual arg parsing to avoid argparse eating command args like /c, &&, etc.
    argv = sys.argv[1:]

    if '--list' in argv:
        asyncio.run(do_list())
        return

    if '--query' in argv:
        idx = argv.index('--query')
        task_id = argv[idx + 1] if idx + 1 < len(argv) else ''
        worker_id = argv[idx + 2] if idx + 2 < len(argv) else ''
        asyncio.run(do_query(task_id, worker_id))
        return

    # Extract known flags
    cwd = ''
    timeout = 3600.0
    poll_interval = 5

    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == '--cwd' and i + 1 < len(argv):
            cwd = argv[i + 1]
            i += 2
        elif argv[i] == '--timeout' and i + 1 < len(argv):
            timeout = float(argv[i + 1])
            i += 2
        elif argv[i] == '--poll' and i + 1 < len(argv):
            poll_interval = int(argv[i + 1])
            i += 2
        elif argv[i] == '--':
            rest.extend(argv[i + 1:])
            break
        else:
            rest.append(argv[i])
            i += 1

    global POLL_INTERVAL
    POLL_INTERVAL = poll_interval

    if len(rest) < 2:
        print("Usage: hako-run [--cwd dir] [--timeout secs] [--poll secs] <worker_id> <command...>")
        print("       hako-run --list")
        print("       hako-run --query <task_id> [worker_id]")
        sys.exit(1)

    worker_id = rest[0]
    cmd_args = rest[1:]

    asyncio.run(do_run(worker_id, cmd_args, cwd, timeout))


if __name__ == '__main__':
    main()
