#!/usr/bin/env python3
"""Quick local run script - installs deps and starts the server."""
import subprocess
import sys
import os

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

def install_backend():
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", f"{BACKEND_DIR}/backend"], check=True)

if __name__ == "__main__":
    install_backend()
    # Start backend and frontend in parallel
    subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"], cwd=f"{BACKEND_DIR}/backend")
    subprocess.run(["npm", "install"], cwd=f"{BACKEND_DIR}/frontend", check=True)
    subprocess.run(["npm", "run", "dev"], cwd=f"{BACKEND_DIR}/frontend", check=True)