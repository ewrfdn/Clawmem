#!/usr/bin/env python3
"""edge-build: Pull latest code and build Edge on devbox.

Usage:
    edge-build                        # pull + build (default)
    edge-build --build-only           # skip pull, just build
    edge-build --pull-only            # just pull, no build  
    edge-build --sync                 # gclient sync + build
    edge-build --full                 # pull + gclient sync + build
    edge-build --config arm64 release # non-default config
"""

import asyncio
import sys
import os
import time

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
from grpc_client import init_client_auth, submit_task, get_task_result, close
from generated import worker_pb2

WORKER_ID = os.environ.get(
    'HAKO_DEFAULT_WORKER',
    'e52287dc4f9acbf1682a76a38f956ec0eeaea7a4fc31a2c5386e206c'
)
SRC_DIR = r'Q:\Edge\src'
POLL_INTERVAL = 10

STATUS_NAMES = {0: 'pending', 1: 'running', 2: 'success', 3: 'failed', 4: 'cancelled'}


def fmt_dur(seconds: float) -> str:
    if seconds < 60: return f"{seconds:.0f}s"
    elif seconds < 3600: return f"{seconds/60:.1f}m"
    else: return f"{seconds/3600:.1f}h"


async def run_step(desc: str, args: list[str], timeout: float = 3600.0) -> bool:
    """Submit a command and poll until done. Returns True on success."""
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"  CMD: {' '.join(args)}")
    print(f"{'='*60}")

    resp = await submit_task(
        worker_id=WORKER_ID,
        task_type=worker_pb2.TASK_TYPE_SYNC,
        timeout=timeout,
        shell=worker_pb2.ShellOperation(args=args, working_dir=SRC_DIR),
    )

    task_id = ''
    if resp.result.output and 'task_id:' in resp.result.output:
        for line in resp.result.output.splitlines():
            if line.startswith('task_id:'):
                task_id = line.split(':', 1)[1].strip()
                break

    if not task_id:
        # Direct result
        ok = resp.result.success
        print(f"  Result: {'OK' if ok else 'FAILED'}")
        if resp.result.output:
            for l in resp.result.output.strip().splitlines()[-20:]:
                print(f"  {l}")
        if resp.result.error:
            print(f"  Error: {resp.result.error[:300]}")
        return ok

    print(f"  Task: {task_id}")
    start = time.time()
    last_s = ''
    while True:
        try:
            r = await get_task_result(task_id=task_id, worker_id=WORKER_ID)
        except Exception as e:
            print(f"  [{fmt_dur(time.time()-start)}] poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL)
            continue

        s = STATUS_NAMES.get(r.status, '?')
        elapsed = fmt_dur(time.time() - start)
        if s != last_s:
            print(f"  [{elapsed}] {s}")
            last_s = s

        if r.status in (2, 3, 4):
            ok = r.status == 2
            print(f"\n  {'✅ PASSED' if ok else '❌ FAILED'} ({elapsed})")
            if r.result.output:
                lines = r.result.output.strip().splitlines()
                show = lines[-30:] if len(lines) > 30 else lines
                if len(lines) > 30:
                    print(f"  ... ({len(lines)-30} lines omitted)")
                for l in show:
                    print(f"  {l}")
            if r.result.error:
                err_lines = r.result.error.strip().splitlines()
                for l in err_lines[-10:]:
                    print(f"  ERR: {l}")
            return ok

        await asyncio.sleep(POLL_INTERVAL)


async def main():
    argv = sys.argv[1:]

    do_pull = True
    do_sync = False
    do_build = True
    arch = 'x64'
    build_type = 'debug'

    i = 0
    while i < len(argv):
        if argv[i] == '--build-only':
            do_pull = False; do_sync = False; i += 1
        elif argv[i] == '--pull-only':
            do_build = False; i += 1
        elif argv[i] == '--sync':
            do_sync = True; i += 1
        elif argv[i] == '--full':
            do_sync = True; i += 1
        elif argv[i] == '--config' and i + 2 < len(argv):
            arch = argv[i+1]; build_type = argv[i+2]; i += 3
        else:
            i += 1

    out_dir = f'out\\win_{arch}_{build_type}_developer_build'

    config = HakoConfig.load()
    await init_client_auth(config)

    print(f"Edge Build Pipeline")
    print(f"Worker: {WORKER_ID[:16]}...")
    print(f"Config: {arch} {build_type}")
    print(f"Output: {SRC_DIR}\\{out_dir}")
    start_all = time.time()

    # Step 1: Pull
    if do_pull:
        ok = await run_step(
            "git pull origin main",
            ['git', 'pull', 'origin', 'main'],
            timeout=1800.0,
        )
        if not ok:
            print("\n⚠️  Pull failed, continuing anyway (may be up to date)...")

    # Step 2: gclient sync
    if do_sync:
        ok = await run_step(
            "gclient sync -D -f",
            ['cmd', '/c', 'gclient sync -D -f'],
            timeout=3600.0,
        )
        if not ok:
            print("\n❌ gclient sync failed, aborting.")
            await close()
            sys.exit(1)

    # Step 3: Build
    if do_build:
        # autogn
        ok = await run_step(
            f"autogn {arch} {build_type}",
            ['cmd', '/c', f'autogn {arch} {build_type}'],
            timeout=300.0,
        )
        if not ok:
            print("\n❌ autogn failed, aborting.")
            await close()
            sys.exit(1)

        # autoninja
        ok = await run_step(
            "autoninja build chrome",
            ['cmd', '/c', f'autoninja -C {out_dir} chrome'],
            timeout=7200.0,
        )
        if ok:
            total = fmt_dur(time.time() - start_all)
            print(f"\n{'='*60}")
            print(f"  🎉 BUILD SUCCEEDED ({total})")
            print(f"  Output: {SRC_DIR}\\{out_dir}")
            print(f"{'='*60}")
        else:
            print("\n❌ BUILD FAILED")
            await close()
            sys.exit(1)

    await close()


if __name__ == '__main__':
    asyncio.run(main())
