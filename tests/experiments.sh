#!/bin/sh
# experiments.sh — тайлангийн 8-р хэсгийн хүснэгтүүдийг дахин гаргах скрипт.
# Ашиглах: sh tests/experiments.sh   → docs/results/*.csv
cd "$(dirname "$0")/.." || exit 1
SIM=./build/threadpool_sim; R=docs/results; mkdir -p $R
py() { python3 -c "import json,sys;s=json.load(open(sys.argv[1]))['summary'];print(','.join(str(s[k]) for k in sys.argv[2:]))" "$@"; }

echo "workers,submitted,rejected,makespan_ms,avg_wait_ms,avg_turnaround_ms,utilization_pct" > $R/exp1_workers.csv
for w in 1 2 4 8 16; do
  $SIM -w $w -q 64 -n 40 -d 100-300 -a 0 -s 1 -o $R/exp1_w$w.json 2>/dev/null
  echo "$w,$(py $R/exp1_w$w.json submitted rejected makespan_ms avg_wait_ms avg_turnaround_ms utilization_pct)" >> $R/exp1_workers.csv
done

echo "queue,submitted,rejected,max_queue,makespan_ms" > $R/exp2_queue.csv
for q in 1 2 4 8 16 20; do
  $SIM -w 2 -q $q -n 20 -d 100 -a 0 -o $R/exp2_q$q.json 2>/dev/null
  echo "$q,$(py $R/exp2_q$q.json submitted rejected max_queue makespan_ms)" >> $R/exp2_queue.csv
done

echo "policy,submitted,rejected_attempts,makespan_ms,avg_wait_ms" > $R/exp3_policy.csv
for p in reject retry; do
  $SIM -w 2 -q 3 -n 20 -d 100 -a 10 -p $p -r 20 -o $R/exp3_$p.json 2>/dev/null
  echo "$p,$(py $R/exp3_$p.json submitted rejected makespan_ms avg_wait_ms)" >> $R/exp3_policy.csv
done
rm -f $R/*.json
for f in $R/*.csv; do echo "== $f"; cat $f; done
