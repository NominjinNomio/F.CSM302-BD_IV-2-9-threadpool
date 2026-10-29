#!/usr/bin/env python3
"""
screenshots.py — Тайлан, Manual-д орох UI-ийн дэлгэцийн зургуудыг бодит ажиллуулалтаас авна.

  python3 tools/server.py --port 8765 &      # сервер ажиллаж байх ёстой
  python3 tools/screenshots.py [--url http://localhost:8765]

Зураг бүр docs/img/shots/ хавтсанд хадгалагдана. Бүх дүрслэл C программын бодит trace.
"""
import argparse
import os
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "latex", "img", "shots")


def union_clip(pg, selectors, pad=8):
    boxes = []
    for s in selectors:
        b = pg.locator(s).first.bounding_box()
        if b:
            boxes.append(b)
    x1 = min(b["x"] for b in boxes) - pad
    y1 = min(b["y"] for b in boxes) - pad
    x2 = max(b["x"] + b["width"] for b in boxes) + pad
    y2 = max(b["y"] + b["height"] for b in boxes) + pad
    return {"x": max(x1, 0), "y": max(y1, 0), "width": x2 - max(x1, 0), "height": y2 - max(y1, 0)}


def shot(pg, name, selectors=None, full=False):
    path = os.path.join(OUT, name + ".png")
    if selectors:
        pg.screenshot(path=path, clip=union_clip(pg, selectors), full_page=True)
    else:
        pg.screenshot(path=path, full_page=full)
    print("  ", name)


def run(pg):
    with pg.expect_response(lambda r: "/api/run" in r.url, timeout=120000):
        pg.click("#run")
    time.sleep(0.5)


def seek(pg, frac=None, ms=None):
    pg.evaluate("([f,m]) => { pause(); seek(m !== null ? m : D.tEnd * f); }", [frac, ms])
    time.sleep(0.25)


def preset(pg, name, w, q, policy="reject"):
    pg.click("#mList")
    pg.select_option("#preset", label=name)
    pg.fill("#workers", str(w))
    pg.fill("#queue", str(q))
    pg.select_option("#policy", policy)


def params(pg, w, q, n, d, a, seed=42, policy="reject"):
    pg.click("#mRandom")
    for k, v in {"#workers": w, "#queue": q, "#ntasks": n, "#dmin": d[0], "#dmax": d[1],
                 "#amin": a[0], "#amax": a[1], "#seed": seed}.items():
        pg.fill(k, str(v))
    pg.select_option("#policy", policy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8765")
    url = ap.parse_args().url + "/?norun&theme=dark"
    os.makedirs(OUT, exist_ok=True)
    MAIN = ["header", "main > .stack:nth-child(2) > .panel:nth-child(1)", ".live",
            "main > .stack:nth-child(2) > .panel:nth-child(3)"]
    LEFT = ["main > .stack:first-child > .panel:nth-child(1)", "main > .stack:first-child > .panel:nth-child(2)"]
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=2, color_scheme="dark")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(url)
        time.sleep(0.8)

        # 1. Анхдагч ажиллуулалт: бүх дэлгэц
        params(pg, 3, 5, 15, (200, 800), (20, 120))
        run(pg)
        seek(pg, 0.45)
        shot(pg, "overview")                                   # viewport
        shot(pg, "default_main", ["header"] + MAIN[1:])
        shot(pg, "settings", LEFT)
        shot(pg, "live_state", [".live"])
        shot(pg, "timeline", ["main > .stack:nth-child(2) > .panel:nth-child(3)"])
        shot(pg, "summary", ["main > .stack:nth-child(2) > .panel:nth-child(4)"])
        pg.evaluate("document.querySelector('#logwrap').scrollTop = 0")
        seek(pg, ms=pg.evaluate("D.steps[8].ms"))
        shot(pg, "event_log", ["main > .stack:nth-child(2) > .panel:nth-child(5)"])

        # 2. Burst + reject
        preset(pg, "burst.txt", 2, 3, "reject")
        run(pg)
        seek(pg, ms=30)
        shot(pg, "burst_reject", MAIN[1:])

        # 3. Burst + retry
        preset(pg, "burst.txt", 2, 3, "retry")
        run(pg)
        seek(pg, 0.5)
        shot(pg, "burst_retry", MAIN[1:])

        # 4. FIFO алхамчлах
        preset(pg, "fifo.txt", 1, 10, "reject")
        run(pg)
        seek(pg, ms=0)
        for _ in range(9):
            pg.click("#next")
            time.sleep(0.05)
        shot(pg, "fifo_step", MAIN[1:])

        # 5. Урт + богино
        preset(pg, "mixed_long_short.txt", 3, 10, "reject")
        run(pg)
        seek(pg, 0.3)
        shot(pg, "long_short", MAIN[1:])

        # 6. 8 worker
        params(pg, 8, 16, 60, (50, 300), (0, 20))
        run(pg)
        seek(pg, 0.35)
        shot(pg, "eight_workers", MAIN[1:])

        # 7. 1 worker vs 4 worker (ижил ачаалал)
        for w in (1, 4):
            params(pg, w, 64, 12, (100, 300), (0, 0), seed=1)
            run(pg)
            seek(pg, 0.5)
            shot(pg, f"compare_w{w}", ["main > .stack:nth-child(2) > .panel:nth-child(3)"])

        # 8. Алдаа
        params(pg, 0, 5, 15, (200, 800), (20, 120))
        pg.click("#run")
        time.sleep(0.8)
        shot(pg, "error_workers0", ["main > .stack:first-child > .panel:nth-child(1)",
                                    "main > .stack:first-child > .panel:nth-child(2)"])
        pg.click("#mList")
        pg.fill("#workers", "2")
        pg.fill("#tasktext", "0 100\n50 abc\n")
        pg.click("#run")
        time.sleep(0.8)
        shot(pg, "error_file", ["main > .stack:first-child > .panel:nth-child(2)"])

        # 9. Offline (сервергүй) trace үзэх
        po = ctx.new_page()
        po.goto("file://" + os.path.join(ROOT, "ui", "index.html") + "?theme=dark")
        time.sleep(0.8)
        po.set_input_files("#file", os.path.join(ROOT, "examples", "sample_trace.json"))
        time.sleep(0.4)
        po.evaluate("() => { pause(); seek(D.tEnd * 0.6); }")
        time.sleep(0.2)
        shot(po, "offline", ["header", "main > .stack:first-child > .panel:nth-child(2)",
                             "main > .stack:nth-child(2) > .panel:nth-child(1)", ".live"])
        print("page errors:", errs)
        b.close()


if __name__ == "__main__":
    main()
