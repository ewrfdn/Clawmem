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
    parser = argparse.ArgumentParser(
        description='Submit commands to HAKO workers and poll results.',
        usage='hako-run [options] <worker_id> [--cwd dir] <command...>',
    )
    parser.add_argument('--list', action='store_true', help='List online workers')
    parser.add_argument('--query', metavar='TASK_ID', help='Query a task result')
    parser.add_argument('--cwd', default='', help='Working directory on worker')
    parser.add_argument('--timeout', type=float, default=3600, help='Timeout in seconds (default: 3600)')
    parser.add_argument('--poll', type=int, default=5, help='Poll interval in seconds (default: 5)')
    parser.add_argument('args', nargs='*', help='worker_id followed by command args')

    parsed = parser.parse_args()

    global POLL_INTERVAL
    POLL_INTERVAL = parsed.poll

    if parsed.list:
        asyncio.run(do_list())
        return

    if parsed.query:
        worker_id = parsed.args[0] if parsed.args else ''
        asyncio.run(do_query(parsed.query, worker_id))
        return

    if len(parsed.args) < 2:
        parser.print_help()
        sys.exit(1)

    worker_id = os.environ.get('HAKO_DEFAULT_WORKER', '') if parsed.args[0].startswith('-') else parsed.args[0]
    cmd_args = parsed.args[1:] if not parsed.args[0].startswith('-') else parsed.args

    if not worker_id:
        print("Error: worker_id required (or set HAKO_DEFAULT_WORKER)")
        sys.exit(1)

    cwd = parsed.cwd
    asyncio.run(do_run(worker_id, cmd_args, cwd, parsed.timeout))


if __name__ == '__main__':
    main()
