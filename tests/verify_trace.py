#!/usr/bin/env python3
"""
verify_trace.py — C программаас гарсан JSON trace-ийг C кодоос ХАМААРАЛГҮЙгээр
дахин шалгана. Ашиглах: python3 tests/verify_trace.py trace.json [--expect k=v ...]

Шалгах зүйлс:
  1. Хүлээн авсан task бүр яг 1 START, 1 END-тэй; татгалзсан task огт ажиллаагүй
  2. START нь SUBMIT-ээс хойш, END нь START-аас хойш
  3. Нэг worker нэгэн зэрэг зөвхөн 1 task (интервал давхцахгүй)
  4. Нэгэн зэрэг ажиллаж буй task ≤ worker-ийн тоо
  5. SUBMIT/START-аас сэргээсэн queue-ийн урт = бүртгэсэн q, мөн ≤ багтаамж
  6. Queue FIFO: START-ийн дараалал = SUBMIT-ийн дараалал
  7. SHUTDOWN-ы дараа шинэ SUBMIT байхгүй; worker бүр WORKER_EXIT хийсэн
--expect: accepted=10, rejected=0, rejected_min=1, accepted_range=3..5, max_running=3
"""
import json
import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        tr = json.load(f)
    p, ev, tasks = tr["params"], tr["events"], tr["tasks"]
    W, Q = p["workers"], p["queue"]
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    submit, start, end = {}, {}, {}
    starts_cnt, ends_cnt = {}, {}
    running = {}           # worker -> task
    qlen = 0
    submit_order, start_order = [], []
    max_run, shutdown_seen, exits = 0, False, set()
    prev_t = -1

    for e in ev:
        t, typ, w, k = e["t"], e["type"], e["w"], e["task"]
        check(t >= prev_t, f"хугацааны дараалал алдагдсан t={t}")
        prev_t = t
        if typ == "SUBMIT":
            check(not shutdown_seen, f"task {k}: SHUTDOWN-ы дараа SUBMIT")
            submit[k] = t
            submit_order.append(k)
            qlen += 1
            check(e["q"] == qlen, f"SUBMIT {k}: q={e['q']} ≠ сэргээсэн {qlen}")
        elif typ == "REJECT":
            check(e["q"] == Q, f"REJECT {k}: queue дүүрээгүй байхад татгалзсан (q={e['q']})")
        elif typ == "START":
            check(k in submit, f"task {k}: SUBMIT-гүйгээр START")
            check(w not in running, f"worker {w}: task {running.get(w)} дуусаагүй байхад {k} эхэлсэн")
            running[w] = k
            start[k] = t
            starts_cnt[k] = starts_cnt.get(k, 0) + 1
            start_order.append(k)
            qlen -= 1
            check(e["q"] == qlen, f"START {k}: q={e['q']} ≠ сэргээсэн {qlen}")
            max_run = max(max_run, len(running))
        elif typ == "END":
            check(running.get(w) == k, f"worker {w}: END {k} нь ажиллаж буй task биш")
            running.pop(w, None)
            end[k] = t
            ends_cnt[k] = ends_cnt.get(k, 0) + 1
        elif typ == "SHUTDOWN":
            shutdown_seen = True
        elif typ == "WORKER_EXIT":
            check(w not in running, f"worker {w}: task ажиллаж байхад гарсан")
            exits.add(w)
        check(0 <= qlen <= Q, f"queue-ийн урт {qlen} хязгаараас гарсан (0..{Q})")

    accepted = [x["id"] for x in tasks if x["accepted"]]
    rejected = [x["id"] for x in tasks if not x["accepted"]]
    for k in accepted:
        check(starts_cnt.get(k) == 1 and ends_cnt.get(k) == 1, f"task {k}: START/END тоо буруу")
        if k in start and k in end:
            check(submit[k] <= start[k] <= end[k], f"task {k}: хугацааны дараалал буруу")
    for k in rejected:
        check(k not in starts_cnt, f"татгалзсан task {k} ажилласан")
    check(max_run <= W, f"нэгэн зэрэг {max_run} > {W} worker")
    check(submit_order == start_order, "FIFO зөрчигдсөн: START-ийн дараалал SUBMIT-тэй ялгаатай")
    check(exits == set(range(W)), f"WORKER_EXIT: {sorted(exits)} (хүлээгдсэн 0..{W-1})")
    check(tr["verify"]["ok"], "C талын шалгалт FAILED")

    # --expect
    stats = {"accepted": len(accepted), "rejected": len(rejected), "max_running": max_run}
    for arg in sys.argv[2:]:
        if arg == "--expect":
            continue
        key, val = arg.split("=")
        if key.endswith("_min"):
            base = key[:-4]
            check(stats[base] >= int(val), f"{base}={stats[base]} < {val}")
        elif key.endswith("_range"):
            base = key[:-6]
            lo, hi = map(int, val.split(".."))
            check(lo <= stats[base] <= hi, f"{base}={stats[base]} ∉ [{lo},{hi}]")
        else:
            check(stats[key] == int(val), f"{key}={stats[key]} ≠ {val}")

    s = tr["summary"]
    print(f"  accepted={len(accepted)} rejected={len(rejected)} max_running={max_run} "
          f"max_queue={s['max_queue']} avg_wait={s['avg_wait_ms']:.1f}ms util={s['utilization_pct']:.1f}%")
    if fails:
        for m in fails[:20]:
            print("  FAIL:", m)
        return 1
    print("  trace шалгалт: OK (" + str(len(ev)) + " үйл явдал)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
