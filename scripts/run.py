#!/usr/bin/env python3
"""一键启动后端 + 前端"""
import subprocess
import sys
import os
import signal
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")

processes = []


def cleanup(sig=None, frame=None):
    for p in processes:
        if p.poll() is None:
            p.terminate()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def main():
    print("启动后端 ...")
    p_backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
        cwd=BACKEND,
    )
    processes.append(p_backend)

    time.sleep(2)

    print("启动前端 ...")
    p_frontend = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=FRONTEND,
    )
    processes.append(p_frontend)

    print()
    print("=" * 40)
    print("  后端: http://localhost:8000")
    print("  前端: http://localhost:5173")
    print("  API文档: http://localhost:8000/api/docs")
    print("  Ctrl+C 停止")
    print("=" * 40)
    print()

    try:
        p_backend.wait()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
