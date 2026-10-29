#!/bin/sh
# run_tests.sh — үндсэн ба boundary/error тестүүд. Ашиглах: make test  (эсвэл sh tests/run_tests.sh)
# Гаралт: тест бүрийн PASS/FAIL, эцэст нь нийт дүн. Trace-ууд build/test_traces/ хавтсанд.

cd "$(dirname "$0")/.." || exit 1
SIM=./build/threadpool_sim
OUT=build/test_traces
mkdir -p "$OUT"
pass=0; fail=0

if [ -t 1 ]; then G='\033[32m'; R='\033[31m'; N='\033[0m'; else G=''; R=''; N=''; fi
ok()  { pass=$((pass+1)); printf "  ${G}PASS${N} %s\n" "$1"; }
bad() { fail=$((fail+1)); printf "  ${R}FAIL${N} %s\n" "$1"; }

# run_ok NAME EXPECT... -- ARGS...   → exit 0 + trace шалгалт + --expect нөхцөл
run_ok() {
    name=$1; shift
    exp=""
    while [ "$1" != "--" ]; do exp="$exp $1"; shift; done; shift
    echo "[$name] $SIM $*"
    if $SIM "$@" -o "$OUT/$name.json" 2> "$OUT/$name.log" && \
       python3 tests/verify_trace.py "$OUT/$name.json" $exp; then ok "$name"
    else tail -5 "$OUT/$name.log"; bad "$name"; fi
}

# run_err NAME PATTERN ARGS...   → exit 2 + алдааны мессеж PATTERN агуулна
run_err() {
    name=$1; pat=$2; shift 2
    $SIM "$@" > /dev/null 2> "$OUT/$name.err"; code=$?
    if [ "$code" -eq 2 ] && grep -q -- "$pat" "$OUT/$name.err"; then
        ok "$name → $(head -1 "$OUT/$name.err")"
    else
        bad "$name (exit=$code): $(head -1 "$OUT/$name.err")"
    fi
}

echo "== 1. Номын жишээ (client.c: pool_init/pool_submit/pool_shutdown) =="
./build/client > "$OUT/client.out" 2>&1
if [ "$(grep -c 'result' "$OUT/client.out")" -eq 5 ] && grep -q 'result = 15' "$OUT/client.out" \
   && grep -q 'result = 300' "$OUT/client.out" && grep -q 'result = 0' "$OUT/client.out"; then
    ok "book_client (5 нийлбэр зөв)"; else cat "$OUT/client.out"; bad "book_client"; fi

echo "== 2. Үндсэн тестүүд =="
run_ok basic_default   accepted=10 rejected=0 max_running=3  -- -f tests/basic.txt
run_ok burst_reject    accepted_range=3..5 rejected_min=5     -- -w 2 -q 3 -f tests/burst.txt
run_ok burst_retry     accepted=10 rejected=0                 -- -w 2 -q 3 -f tests/burst.txt -p retry -r 20
run_ok fifo_one_worker accepted=6 max_running=1               -- -w 1 -f tests/fifo.txt
run_ok long_short_mix  accepted=8                             -- -w 3 -f tests/mixed_long_short.txt
run_ok random_seeded   accepted=20                            -- -w 4 -q 8 -n 20 -d 50-200 -a 10-40 -s 7

echo "== 3. Boundary тестүүд =="
run_ok queue_cap_1     rejected_min=1                         -- -w 1 -q 1 -n 6 -d 100 -a 0
run_ok more_workers    accepted=3 max_running=3               -- -w 8 -q 4 -n 3 -d 100 -a 0
run_ok max_workers_64  accepted=64                            -- -w 64 -q 64 -n 64 -d 50 -a 0
run_ok single_task     accepted=1                             -- -w 1 -q 1 -n 1 -d 1
run_ok stress_500      accepted=500                           -- -w 8 -q 16 -n 500 -d 1-3 -a 0 -p retry -r 1

echo "== 4. Буруу оролтын тестүүд (exit 2 + ойлгомжтой мессеж) =="
run_err err_workers_0    "worker-ийн тоо"   -w 0
run_err err_workers_65   "worker-ийн тоо"   -w 65
run_err err_queue_0      "queue-ийн"        -q 0
run_err err_queue_text   "queue-ийн"        -q abc
run_err err_tasks_0      "task-ийн тоо"     -n 0
run_err err_dur_0        "-d буруу"         -d 0
run_err err_dur_order    "MIN нь MAX"       -d 500-100
run_err err_gap_neg      "-a буруу"         -a -5
run_err err_policy       "reject"           -p fifo
run_err err_missing_val  "утга өгөөгүй"     -w
run_err err_unknown_opt  "Танигдаагүй"      -x 1
run_err err_file_missing "нээж чадсангүй"   -f tests/no_such_file.txt
run_err err_file_number  "arrival_ms буруу" -f tests/bad_number.txt
run_err err_file_sorted  "өсөхгүй дарааллаар" -f tests/bad_unsorted.txt
run_err err_file_columns "2 тоотой"         -f tests/bad_columns.txt
run_err err_file_dur0    "duration_ms буруу" -f tests/bad_duration.txt
run_err err_file_empty   "нэг ч task"       -f tests/bad_empty.txt

echo
echo "Нийт: $pass PASS, $fail FAIL"
[ "$fail" -eq 0 ]
