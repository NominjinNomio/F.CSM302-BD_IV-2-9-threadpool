#!/usr/bin/env python3
"""
server.py — Interactive UI-г C thread pool-тэй холбох жижиг HTTP сервер (зөвхөн Python stdlib).

  python3 tools/server.py [--port 8000]   →   http://localhost:8000

UI дээр "Ажиллуулах" дарахад сервер build/threadpool_sim бинарыг өгсөн параметрээр
БОДИТООР ажиллуулж, гарсан JSON trace-ийг UI-д буцаана. Симуляц JS дээр хийгдэхгүй —
дүрслэл нь C программын жинхэнэ үйл явдлын бүртгэлээс зурагдана.

API:
  GET  /api/health    → {"ok": true, "binary": "..."}
  GET  /api/presets   → tests/*.txt (bad_*.txt-ээс бусад) task-ийн файлууд
  POST /api/run       → {"workers","queue","tasks","dmin","dmax","amin","amax",
                         "policy","retry_ms","seed","task_text"} → trace JSON
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(ROOT, "build", "threadpool_sim")
UI_DIR = os.path.join(ROOT, "ui")
TESTS_DIR = os.path.join(ROOT, "tests")
MAX_UI_TASKS = 2000          # UI-д зурахад хэт олон bar-аас сэргийлнэ
MAX_EST_SECONDS = 60         # нэг ажиллуулалт хамгийн ихдээ ~1 минут
RUN_TIMEOUT = 120

STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8")}


def as_int(params, key, default):
    v = params.get(key, default)
    if isinstance(v, bool):
        raise ValueError(f"'{key}' бүхэл тоо байх ёстой")
    if isinstance(v, (int, float)) and float(v).is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    raise ValueError(f"'{key}' талбарын утга бүхэл тоо биш: {v!r}")


def build_command(params, tmpdir):
    """UI-ийн параметрийг CLI аргумент болгоно. Утгын хязгаарыг C программ өөрөө шалгана."""
    cmd = [BINARY, "-w", str(as_int(params, "workers", 3)), "-q", str(as_int(params, "queue", 10))]
    policy = params.get("policy", "reject")
    cmd += ["-p", str(policy), "-r", str(as_int(params, "retry_ms", 20))]
    workers = max(1, as_int(params, "workers", 3))

    text = (params.get("task_text") or "").strip()
    if text:
        lines = [l for l in text.splitlines() if l.split("#")[0].strip()]
        if len(lines) > MAX_UI_TASKS:
            raise ValueError(f"UI-д хамгийн ихдээ {MAX_UI_TASKS} task зурна (одоо {len(lines)}).")
        est = 0
        for l in lines:
            parts = l.split("#")[0].split()
            if len(parts) == 2 and parts[1].isdigit():
                est += int(parts[1])
        if est / workers / 1000 > MAX_EST_SECONDS:
            raise ValueError(f"Тооцоолсон хугацаа ~{est/workers/1000:.0f} сек — {MAX_EST_SECONDS} секундээс "
                             "хэтэрнэ. Task-ийн хугацааг багасгах эсвэл worker нэмнэ үү.")
        path = os.path.join(tmpdir, "tasks.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        cmd += ["-f", path]
    else:
        n = as_int(params, "tasks", 12)
        dmin, dmax = as_int(params, "dmin", 200), as_int(params, "dmax", 800)
        amin, amax = as_int(params, "amin", 50), as_int(params, "amax", 150)
        if n > MAX_UI_TASKS:
            raise ValueError(f"UI-д хамгийн ихдээ {MAX_UI_TASKS} task зурна.")
        if n > 0 and dmax > 0 and n * (dmin + dmax) / 2 / workers / 1000 > MAX_EST_SECONDS:
            raise ValueError(f"Тооцоолсон хугацаа ~{n*(dmin+dmax)/2/workers/1000:.0f} сек — "
                             f"{MAX_EST_SECONDS} секундээс хэтэрнэ. Task/хугацааг багасгана уу.")
        cmd += ["-n", str(n), "-d", f"{dmin}-{dmax}", "-a", f"{amin}-{amax}",
                "-s", str(as_int(params, "seed", 42))]
    return cmd


class Handler(BaseHTTPRequestHandler):
    server_version = "ThreadPoolUI/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[ui] " + (fmt % args) + "\n")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/health":
            return self.send_json(200, {"ok": os.path.exists(BINARY), "binary": os.path.relpath(BINARY, ROOT)})
        if path == "/api/presets":
            items = []
            for name in sorted(os.listdir(TESTS_DIR)):
                if name.endswith(".txt") and not name.startswith("bad_"):
                    with open(os.path.join(TESTS_DIR, name), encoding="utf-8") as f:
                        items.append({"name": name, "text": f.read()})
            return self.send_json(200, {"presets": items})
        if path in STATIC:
            fname, ctype = STATIC[path]
            with open(os.path.join(UI_DIR, fname), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self.send_json(404, {"ok": False, "error": "олдсонгүй"})

    def do_POST(self):
        if self.path != "/api/run":
            return self.send_json(404, {"ok": False, "error": "олдсонгүй"})
        if not os.path.exists(BINARY):
            return self.send_json(500, {"ok": False, "error": "build/threadpool_sim алга. Эхлээд 'make' ажиллуулна уу."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("Хүсэлт хэт том байна.")
            params = json.loads(self.rfile.read(length) or b"{}")
            with tempfile.TemporaryDirectory() as tmp:
                cmd = build_command(params, tmp) + ["-o", "-"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT, cwd=ROOT)
        except (ValueError, json.JSONDecodeError) as e:
            return self.send_json(400, {"ok": False, "error": str(e)})
        except subprocess.TimeoutExpired:
            return self.send_json(504, {"ok": False, "error": f"Ажиллуулалт {RUN_TIMEOUT} секундэд дуусаагүй."})

        # Түр файлын замыг хэрэглэгчид ойлгомжтой нэрээр харуулна
        tmp_task = os.path.join(tmp, "tasks.txt")
        pretty = lambda s: s.replace(tmp_task, "<task жагсаалт>")
        proc.stderr = pretty(proc.stderr)
        display_cmd = pretty(" ".join(os.path.relpath(c, ROOT) if c.startswith(ROOT) else c for c in cmd))
        if proc.returncode == 2:   # C программын оролтын шалгалт
            return self.send_json(400, {"ok": False, "error": proc.stderr.strip(), "command": display_cmd})
        try:
            trace = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return self.send_json(500, {"ok": False, "error": "Trace уншиж чадсангүй:\n" + proc.stderr[-2000:],
                                        "command": display_cmd})
        self.send_json(200, {"ok": True, "exit_code": proc.returncode, "command": display_cmd,
                             "log": proc.stderr, "trace": trace})


def main():
    ap = argparse.ArgumentParser(description="Thread pool worker-activity UI сервер")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if not os.path.exists(BINARY):
        print("Анхааруулга: build/threadpool_sim алга — эхлээд 'make' ажиллуулна уу.", file=sys.stderr)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"UI: http://localhost:{args.port}   (зогсоох: Ctrl+C)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер зогслоо.")


if __name__ == "__main__":
    main()
