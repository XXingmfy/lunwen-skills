"""自动探测并启动仓库里的 Web 系统，返回可访问的 baseUrl。

当前自动支持：Python 后端（FastAPI / Flask，含 SQLite seed 的毕设项目）。
- 若 frontend/dist 存在，通常后端会直接托管；否则尝试 npm install + npm run build。
Java/Spring 等其它栈不自动启动，请用 --url 指定已运行的系统地址。

用法（也可作为模块 import）：
  python -I provision.py <源码目录> [--port 8037] [--log <日志路径>] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def pick_port(preferred: int | None = None) -> int:
    if preferred:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_backend(src: Path) -> Path | None:
    for name in ("backend", "server", "api"):
        d = src / name
        if d.is_dir() and (
            (d / "requirements.txt").exists() or (d / "main.py").exists() or (d / "app.py").exists()
        ):
            return d
    if any((src / f).exists() for f in ("requirements.txt", "main.py", "app.py")):
        return src
    return None


def is_java(backend: Path) -> bool:
    return (backend / "pom.xml").exists() or (backend / "build.gradle").exists()


def python_target(backend: Path) -> str | None:
    if (backend / "app" / "main.py").exists():
        return "app.main:app"
    if (backend / "main.py").exists():
        return "main:app"
    if (backend / "app.py").exists():
        return "app:app"
    return None


def _pyhas(mods: str) -> bool:
    p = subprocess.run([sys.executable, "-c", f"import {mods}"], capture_output=True, text=True)
    return p.returncode == 0


def ensure_deps(backend: Path, log=print):
    req = backend / "requirements.txt"
    if not req.exists():
        return
    if _pyhas("fastapi,uvicorn") or _pyhas("flask"):
        return
    log(f"[provision] 安装 Python 依赖: {req}")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
        cwd=backend,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ensure_frontend_dist(src: Path, backend: Path, log=print) -> bool:
    if (src / "frontend" / "dist").exists() or (backend.parent / "frontend" / "dist").exists():
        return True
    fe = src / "frontend"
    if (fe / "package.json").exists():
        npm = subprocess.run(["where", "npm"], capture_output=True, text=True, shell=False)
        npm_bin = npm.stdout.splitlines()[0].strip() if npm.returncode == 0 and npm.stdout.strip() else None
        if not npm_bin:
            log("[provision] 未找到 npm，无法构建前端")
            return False
        log("[provision] 构建前端: npm install && npm run build")
        subprocess.run([npm_bin, "install", "--no-audit", "--no-fund"], cwd=fe, capture_output=True, text=True)
        p = subprocess.run([npm_bin, "run", "build"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return (fe / "dist").exists() and p.returncode == 0
    return False


def _probe(base: str) -> bool:
    import urllib.request

    for path in ("/api/health", "/health", "/", ""):
        try:
            with urllib.request.urlopen(base.rstrip("/") + path, timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            continue
    return False


def start_python(backend: Path, port: int, log_path: Path, log=print):
    target = python_target(backend)
    if not target:
        raise RuntimeError(f"无法在 {backend} 找到 FastAPI/Flask 入口（main.py / app/main.py）")
    (backend / "data").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("JWT_SECRET", "webapp-walkthrough-dev")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(log_path, "ab")
    f.write(f"\n\n==== start {time.strftime('%Y-%m-%d %H:%M:%S')} uvicorn {target} :{port} ====\n".encode())
    f.flush()
    cmd = [sys.executable, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(cmd, cwd=str(backend), env=env, stdout=f, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        if proc.poll() is not None:
            raise RuntimeError(f"后端启动即退出，见日志 {log_path}")
        if _probe(base):
            return proc, base
        time.sleep(0.5)
    raise RuntimeError(f"后端 60 秒内未就绪，见日志 {log_path}")


def provision(src: str | Path, port: int | None = None, log_path: str | Path | None = None, log=print):
    """启动系统并返回 (proc, baseUrl)。"""
    src = Path(src)
    backend = find_backend(src)
    if backend is None:
        raise RuntimeError(f"在 {src} 下没找到可识别的后端目录（backend/ + requirements.txt）")
    if is_java(backend):
        raise RuntimeError(
            "该仓库是 Java/Spring 后端，自动启动成本高。请手动启动系统后用 --url 指定地址，"
            "例如 --url http://127.0.0.1:8080"
        )
    ensure_deps(backend, log=log)
    ensure_frontend_dist(src, backend, log=log)
    port = pick_port(port)
    log_path = Path(log_path) if log_path else (Path.cwd() / f"uvicorn-{port}.log")
    proc, base = start_python(backend, port, log_path, log=log)
    log(f"[provision] 系统已启动: {base} (pid {proc.pid})")
    return proc, base


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        proc, base = provision(a.src, a.port, a.log)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False) if a.json else f"[错误] {e}")
        return 1
    print(json.dumps({"ok": True, "baseUrl": base, "pid": proc.pid}, ensure_ascii=False) if a.json else base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
