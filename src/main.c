/*
 * main.c — thread pool-ийн туршилтын программ (симулятор + trace экспорт).
 *
 * Хэрэглэгч worker-ийн тоо, queue-ийн багтаамж, task-ийн тоо/хугацаа/ирэх
 * давтамж эсвэл task-ийн файлыг өгч ажиллуулна. Task бүр бодитоор worker
 * thread дээр ажиллаж (nanosleep), бүх үйл явдлыг JSON trace болгон гаргана.
 * Энэ trace-ийг UI (ui/index.html) "Worker activity" дүрслэл болгон харуулна.
 *
 * Гарах код: 0 — OK, 2 — буруу оролт, 3 — ажиллах үеийн алдаа, 4 — шалгалт унасан.
 */
#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE   /* dispatch_semaphore, clock_gettime */
#endif
#include "threadpool.h"

#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_TASKS     10000
#define MAX_DUR_MS    60000
#define MAX_GAP_MS    60000
#define MAX_LINE      512

typedef struct {
    int    id;
    long   arrival_ms;   /* pool_init-ээс хойш хэзээ submit хийх */
    long   duration_ms;  /* task-ийн ажиллах хугацаа */
    int    attempts;     /* submit оролдлогын тоо */
    int    accepted;     /* 1 — queue-д орсон */
    volatile long runs;  /* хэдэн удаа ажилласан (яг 1 байх ёстой) */
    long   result;       /* task-ийн тооцоолсон утга (зөв ажилласныг шалгах) */
} task_spec;

static task_spec *tasks;
static int        ntasks;
static pthread_mutex_t runs_mutex = PTHREAD_MUTEX_INITIALIZER;
static int        verbose;

/* ---------------- Туслах функцууд ------------------------------------------ */
static void sleep_ms(long ms)
{
    if (ms <= 0) return;
    struct timespec req = { ms / 1000, (ms % 1000) * 1000000L }, rem;
    while (nanosleep(&req, &rem) == -1 && errno == EINTR) req = rem;
}

static void die_input(const char *fmt, const char *a, const char *b)
{
    fprintf(stderr, "Алдаа: ");
    fprintf(stderr, fmt, a, b);
    fprintf(stderr, "\n'-h' сонголтоор тусламж харна уу.\n");
    exit(2);
}

/* Бүхэл тоог бүрэн шалгаж уншина ("12abc", "", " " зэргийг хүлээж авахгүй). */
static int parse_long(const char *s, long lo, long hi, long *out)
{
    if (!s || !*s) return -1;
    char *end; errno = 0;
    long v = strtol(s, &end, 10);
    if (errno || *end != '\0' || v < lo || v > hi) return -1;
    *out = v;
    return 0;
}

/* "MIN" эсвэл "MIN-MAX" хэлбэрийн мужийг уншина. */
static int parse_range(const char *s, long lo, long hi, long *mn, long *mx)
{
    char buf[64];
    if (!s || strlen(s) >= sizeof buf) return -1;
    strcpy(buf, s);
    char *dash = strchr(buf, '-');
    if (dash) {
        *dash = '\0';
        if (parse_long(buf, lo, hi, mn) || parse_long(dash + 1, lo, hi, mx)) return -1;
        if (*mn > *mx) return -2;
    } else {
        if (parse_long(buf, lo, hi, mn)) return -1;
        *mx = *mn;
    }
    return 0;
}

static unsigned long rng_state;
static long rnd_between(long a, long b)   /* [a, b] — xorshift, seed-ээр давтагдана */
{
    rng_state ^= rng_state << 13; rng_state ^= rng_state >> 7; rng_state ^= rng_state << 17;
    if (b <= a) return a;
    return a + (long)(rng_state % (unsigned long)(b - a + 1));
}

/* ---------------- Task-ийн функц (worker thread дээр ажиллана) ------------- */
static void work(void *p)
{
    task_spec *t = p;
    if (verbose) fprintf(stderr, "  task %d эхэлсэн (%ld ms)\n", t->id, t->duration_ms);

    sleep_ms(t->duration_ms);                 /* номын зөвлөмж: sleep-ээр ажлыг дуурайх */
    long s = 0;
    for (long i = 1; i <= t->id + 1; i++) s += i;   /* шалгах боломжтой үр дүн */
    t->result = s;

    pthread_mutex_lock(&runs_mutex);
    t->runs++;
    pthread_mutex_unlock(&runs_mutex);
}

/* ---------------- Task-ийн файл уншиx -------------------------------------- */
static void load_task_file(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) die_input("'%s' файлыг нээж чадсангүй (%s).", path, strerror(errno));

    char line[MAX_LINE];
    int lineno = 0;
    long prev_arrival = 0;
    tasks = calloc(MAX_TASKS, sizeof *tasks);
    if (!tasks) { fprintf(stderr, "Санах ой хүрэлцсэнгүй\n"); exit(3); }

    while (fgets(line, sizeof line, f)) {
        lineno++;
        char *hash = strchr(line, '#');
        if (hash) *hash = '\0';
        char a[64], d[64], extra[64];
        int k = sscanf(line, "%63s %63s %63s", a, d, extra);
        if (k <= 0) continue;                     /* хоосон / тайлбар мөр */
        char where[96];
        snprintf(where, sizeof where, "%s:%d", path, lineno);
        if (k != 2)
            die_input("%s — мөр бүр 'arrival_ms duration_ms' гэсэн 2 тоотой байх ёстой.%s", where, "");
        long av, dv;
        if (parse_long(a, 0, 3600000, &av))
            die_input("%s — arrival_ms буруу ('%s'). 0..3600000 бүхэл тоо байна.", where, a);
        if (parse_long(d, 1, MAX_DUR_MS, &dv))
            die_input("%s — duration_ms буруу ('%s'). 1..60000 бүхэл тоо байна.", where, d);
        if (av < prev_arrival)
            die_input("%s — arrival_ms өсөхгүй дарааллаар байна ('%s'). Эрэмбэлэгдсэн байх ёстой.", where, a);
        if (ntasks >= MAX_TASKS)
            die_input("%s — task-ийн тоо 10000-аас хэтэрсэн.%s", where, "");
        prev_arrival = av;
        tasks[ntasks].id = ntasks;
        tasks[ntasks].arrival_ms = av;
        tasks[ntasks].duration_ms = dv;
        ntasks++;
    }
    fclose(f);
    if (ntasks == 0) die_input("'%s' файлд нэг ч task алга.%s", path, "");
}

/* ---------------- JSON гаралт ---------------------------------------------- */
static void json_str(FILE *o, const char *s)
{
    fputc('"', o);
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') fprintf(o, "\\%c", c);
        else if (c < 0x20) fprintf(o, "\\u%04x", c);
        else fputc(c, o);
    }
    fputc('"', o);
}

typedef struct { const char *name; int ok; char detail[200]; } check;

static void usage(const char *prog)
{
    printf(
"Хэрэглээ: %s [сонголтууд]\n"
"  -w N        worker thread-ийн тоо (1..%d, анхдагч %d)\n"
"  -q N        queue-ийн багтаамж (1..%d, анхдагч %d)\n"
"  -n N        task-ийн тоо (1..%d, анхдагч 12)\n"
"  -d A[-B]    task-ийн хугацаа ms (1..%d, анхдагч 200-800)\n"
"  -a A[-B]    дараалсан task-уудын ирэх зай ms (0..%d, анхдагч 50-150)\n"
"  -f FILE     task-ийн файл: мөр бүр 'arrival_ms duration_ms' (-n -d -a-г орлоно)\n"
"  -p POLICY   queue дүүрэх үед: reject (номын дагуу 1 буцааж хаяна) | retry\n"
"  -r MS       retry хоорондын зай ms (1..10000, анхдагч 20)\n"
"  -s SEED     санамсаргүй тооны seed (анхдагч 42)\n"
"  -o FILE     JSON trace бичих файл ('-' бол stdout)\n"
"  -v          task бүрийг stderr-д хэвлэх\n"
"  -h          энэ тусламж\n"
"Жишээ: %s -w 3 -q 5 -n 20 -d 100-400 -a 20-60 -o trace.json\n",
        prog, POOL_MAX_THREADS, NUMBER_OF_THREADS, POOL_MAX_QUEUE, QUEUE_SIZE,
        MAX_TASKS, MAX_DUR_MS, MAX_GAP_MS, prog);
}

int main(int argc, char **argv)
{
    long w = NUMBER_OF_THREADS, q = QUEUE_SIZE, n = 12, dmin = 200, dmax = 800,
         amin = 50, amax = 150, seed = 42, retry_ms = 20;
    const char *file = NULL, *out = NULL, *policy = "reject";
    int nflag = 0;

    for (int i = 1; i < argc; i++) {
        const char *o = argv[i];
        const char *v = (i + 1 < argc) ? argv[i + 1] : NULL;
        int r;
        if (!strcmp(o, "-h") || !strcmp(o, "--help")) { usage(argv[0]); return 0; }
        else if (!strcmp(o, "-v")) { verbose = 1; continue; }
        if (o[0] != '-' || strlen(o) != 2) die_input("Танигдаагүй аргумент '%s'.%s", o, "");
        if (!v) die_input("'%s' сонголтод утга өгөөгүй байна.%s", o, "");
        i++;
        switch (o[1]) {
        case 'w': if (parse_long(v, 1, POOL_MAX_THREADS, &w))
                      die_input("-w буруу ('%s'): worker-ийн тоо 1..64 бүхэл тоо байна.%s", v, "");
                  break;
        case 'q': if (parse_long(v, 1, POOL_MAX_QUEUE, &q))
                      die_input("-q буруу ('%s'): queue-ийн багтаамж 1..4096 байна.%s", v, "");
                  break;
        case 'n': if (parse_long(v, 1, MAX_TASKS, &n))
                      die_input("-n буруу ('%s'): task-ийн тоо 1..10000 байна.%s", v, "");
                  nflag = 1; break;
        case 'd': r = parse_range(v, 1, MAX_DUR_MS, &dmin, &dmax);
                  if (r == -2) die_input("-d буруу ('%s'): MIN нь MAX-аас их байж болохгүй.%s", v, "");
                  if (r) die_input("-d буруу ('%s'): 'MIN' эсвэл 'MIN-MAX', 1..60000 ms.%s", v, "");
                  break;
        case 'a': r = parse_range(v, 0, MAX_GAP_MS, &amin, &amax);
                  if (r == -2) die_input("-a буруу ('%s'): MIN нь MAX-аас их байж болохгүй.%s", v, "");
                  if (r) die_input("-a буруу ('%s'): 'MIN' эсвэл 'MIN-MAX', 0..60000 ms.%s", v, "");
                  break;
        case 'f': file = v; break;
        case 'p': if (strcmp(v, "reject") && strcmp(v, "retry"))
                      die_input("-p буруу ('%s'): 'reject' эсвэл 'retry' байна.%s", v, "");
                  policy = v; break;
        case 'r': if (parse_long(v, 1, 10000, &retry_ms))
                      die_input("-r буруу ('%s'): 1..10000 ms.%s", v, "");
                  break;
        case 's': if (parse_long(v, 0, LONG_MAX, &seed))
                      die_input("-s буруу ('%s'): сөрөг биш бүхэл тоо.%s", v, "");
                  break;
        case 'o': out = v; break;
        default:  die_input("Танигдаагүй сонголт '%s'.%s", o, "");
        }
    }
    if (file && nflag)
        fprintf(stderr, "Анхааруулга: -f өгсөн тул -n/-d/-a-г тооцохгүй.\n");

    /* ---- Task-уудыг бэлтгэх ---- */
    if (file) {
        load_task_file(file);
    } else {
        ntasks = (int)n;
        tasks = calloc((size_t)ntasks, sizeof *tasks);
        if (!tasks) { fprintf(stderr, "Санах ой хүрэлцсэнгүй\n"); return 3; }
        rng_state = (unsigned long)seed * 2654435761UL + 88172645463325252UL;
        long t = 0;
        for (int i = 0; i < ntasks; i++) {
            if (i > 0) t += rnd_between(amin, amax);
            tasks[i].id = i;
            tasks[i].arrival_ms = t;
            tasks[i].duration_ms = rnd_between(dmin, dmax);
        }
    }
    int retry = !strcmp(policy, "retry");

    /* ---- Ажиллуулах ---- */
    if (trace_enable((size_t)ntasks * 64 + 4 * (size_t)w + 64) != 0) {
        fprintf(stderr, "Trace-ийн санах ой хүрэлцсэнгүй\n"); return 3;
    }
    if (pool_init_ex((int)w, (int)q) != 0) { fprintf(stderr, "pool_init амжилтгүй\n"); return 3; }

    for (int i = 0; i < ntasks; i++) {
        task_spec *t = &tasks[i];
        long wait = t->arrival_ms - trace_now_us() / 1000;
        if (wait > 0) sleep_ms(wait);
        for (;;) {
            t->attempts++;
            int rc = pool_submit_id(work, t, t->id);
            if (rc == POOL_OK) { t->accepted = 1; break; }
            if (rc == POOL_ERR) { fprintf(stderr, "pool_submit алдаа (task %d)\n", t->id); return 3; }
            if (!retry) {
                if (verbose) fprintf(stderr, "  task %d: queue дүүрсэн → татгалзав\n", t->id);
                break;
            }
            sleep_ms(retry_ms);
        }
    }
    pool_shutdown();

    /* ---- Үр дүн ба шалгалт ---- */
    pool_stats st;
    pool_get_stats(&st);
    size_t nev;
    const pool_event *ev = trace_events(&nev);

    long long *sub = calloc((size_t)ntasks, sizeof *sub), *beg = calloc((size_t)ntasks, sizeof *beg),
              *fin = calloc((size_t)ntasks, sizeof *fin);
    int *running_task = calloc((size_t)w, sizeof *running_task);
    int *starts = calloc((size_t)ntasks, sizeof *starts), *ends = calloc((size_t)ntasks, sizeof *ends);
    if (!sub || !beg || !fin || !running_task || !starts || !ends) { fprintf(stderr, "Санах ой\n"); return 3; }
    for (int i = 0; i < w; i++) running_task[i] = -1;

    int running = 0, max_running = 0, max_q = 0;
    int bad_worker = 0, bad_order = 0, bad_q = 0;
    long long busy_us = 0, first_sub = -1, last_end = 0, shutdown_t = -1;
    for (size_t i = 0; i < nev; i++) {
        const pool_event *e = &ev[i];
        if (e->qlen > max_q) max_q = e->qlen;
        if (e->qlen > q) bad_q = 1;
        switch (e->type) {
        case EV_SUBMIT: sub[e->task] = e->t_us; if (first_sub < 0) first_sub = e->t_us; break;
        case EV_START:
            if (running_task[e->worker] != -1) bad_worker = 1;     /* нэг worker давхар ажил */
            running_task[e->worker] = e->task;
            beg[e->task] = e->t_us; starts[e->task]++;
            if (e->t_us < sub[e->task] || !tasks[e->task].accepted) bad_order = 1;
            if (++running > max_running) max_running = running;
            break;
        case EV_END:
            if (running_task[e->worker] != e->task) bad_worker = 1;
            running_task[e->worker] = -1;
            fin[e->task] = e->t_us; ends[e->task]++;
            busy_us += e->t_us - beg[e->task];
            if (e->t_us > last_end) last_end = e->t_us;
            running--;
            break;
        case EV_SHUTDOWN: shutdown_t = e->t_us; break;
        default: break;
        }
    }

    int once_ok = 1, result_ok = 1, rejected_ran = 0;
    double sum_wait = 0, sum_tat = 0, max_wait = 0;
    int acc = 0;
    for (int i = 0; i < ntasks; i++) {
        if (tasks[i].accepted) {
            acc++;
            if (tasks[i].runs != 1 || starts[i] != 1 || ends[i] != 1) once_ok = 0;
            long expect = (long)(i + 1) * (i + 2) / 2;
            if (tasks[i].result != expect) result_ok = 0;
            double wv = (beg[i] - sub[i]) / 1000.0;
            sum_wait += wv; if (wv > max_wait) max_wait = wv;
            sum_tat += (fin[i] - sub[i]) / 1000.0;
        } else if (tasks[i].runs != 0) rejected_ran = 1;
    }
    double makespan_ms = first_sub >= 0 ? (last_end - first_sub) / 1000.0 : 0;
    double util = makespan_ms > 0 ? busy_us / 1000.0 / (w * makespan_ms) * 100.0 : 0;

    check checks[8]; int nc = 0;
#define CHECK(nm, cond, ...) do { checks[nc].name = nm; checks[nc].ok = (cond); \
        snprintf(checks[nc].detail, sizeof checks[nc].detail, __VA_ARGS__); nc++; } while (0)
    CHECK("accepted_run_once", once_ok, "хүлээн авсан %d task бүр яг 1 удаа START/END хийсэн", acc);
    CHECK("results_correct", result_ok, "task бүрийн тооцоолсон үр дүн хүлээгдсэнтэй тэнцүү");
    CHECK("rejected_not_run", !rejected_ran, "татгалзсан %ld task огт ажиллаагүй", st.rejected);
    CHECK("worker_exclusive", !bad_worker, "нэг worker нэгэн зэрэг 1-ээс олон task ажиллуулаагүй");
    CHECK("concurrency_le_workers", max_running <= w, "нэгэн зэрэг ажилласан дээд тоо %d ≤ %ld worker", max_running, w);
    CHECK("queue_le_capacity", !bad_q && max_q <= q, "queue-ийн дээд урт %d ≤ багтаамж %ld", max_q, q);
    CHECK("start_after_submit", !bad_order, "task бүр submit-ийн дараа эхэлсэн");
    CHECK("counts_consistent", st.submitted == st.completed && st.submitted == acc,
          "submitted=%ld, completed=%ld, accepted=%d", st.submitted, st.completed, acc);
    int all_ok = 1;
    for (int i = 0; i < nc; i++) all_ok &= checks[i].ok;

    /* ---- Хүний уншихуйц хураангуй (stderr) ---- */
    fprintf(stderr,
        "\n== Thread pool: %ld worker, queue %ld, %d task, policy=%s ==\n"
        "Хүлээн авсан  : %ld\nТатгалзсан    : %ld\nДууссан       : %ld\n"
        "Дундаж хүлээлт: %.1f ms (дээд %.1f ms)\nДундаж turnaround: %.1f ms\n"
        "Makespan      : %.1f ms\nWorker ашиглалт: %.1f %%\nQueue дээд урт: %d\n",
        w, q, ntasks, policy, st.submitted, st.rejected, st.completed,
        acc ? sum_wait / acc : 0, max_wait, acc ? sum_tat / acc : 0, makespan_ms, util, max_q);
    fprintf(stderr, "Worker бүрийн дууссан task:");
    for (int i = 0; i < w; i++) fprintf(stderr, " W%d=%ld", i, st.per_worker_completed[i]);
    fprintf(stderr, "\n");
    for (int i = 0; i < nc; i++)
        fprintf(stderr, "[%s] %s — %s\n", checks[i].ok ? " OK " : "FAIL", checks[i].name, checks[i].detail);
    fprintf(stderr, "VERIFY: %s\n", all_ok ? "OK" : "FAILED");

    /* ---- JSON trace ---- */
    if (out) {
        FILE *o = strcmp(out, "-") ? fopen(out, "w") : stdout;
        if (!o) { fprintf(stderr, "'%s' файлд бичиж чадсангүй: %s\n", out, strerror(errno)); return 3; }
        fprintf(o, "{\"version\":1,\n\"params\":{\"workers\":%ld,\"queue\":%ld,\"tasks\":%d,"
                   "\"policy\":", w, q, ntasks);
        json_str(o, policy);
        fprintf(o, ",\"seed\":%ld,\"duration\":[%ld,%ld],\"gap\":[%ld,%ld],\"retry_ms\":%ld,\"file\":",
                seed, dmin, dmax, amin, amax, retry_ms);
        if (file) json_str(o, file); else fputs("null", o);
        fprintf(o, "},\n\"tasks\":[");
        for (int i = 0; i < ntasks; i++)
            fprintf(o, "%s\n{\"id\":%d,\"arrival_ms\":%ld,\"duration_ms\":%ld,\"accepted\":%s,\"attempts\":%d,\"runs\":%ld}",
                    i ? "," : "", i, tasks[i].arrival_ms, tasks[i].duration_ms,
                    tasks[i].accepted ? "true" : "false", tasks[i].attempts, tasks[i].runs);
        fprintf(o, "],\n\"events\":[");
        for (size_t i = 0; i < nev; i++)
            fprintf(o, "%s\n{\"t\":%lld,\"type\":\"%s\",\"w\":%d,\"task\":%d,\"q\":%d}",
                    i ? "," : "", ev[i].t_us, trace_type_name(ev[i].type), ev[i].worker, ev[i].task, ev[i].qlen);
        fprintf(o, "],\n\"summary\":{\"submitted\":%ld,\"rejected\":%ld,\"completed\":%ld,"
                   "\"avg_wait_ms\":%.3f,\"max_wait_ms\":%.3f,\"avg_turnaround_ms\":%.3f,"
                   "\"makespan_ms\":%.3f,\"utilization_pct\":%.2f,\"max_queue\":%d,\"max_running\":%d,"
                   "\"shutdown_us\":%lld,\"per_worker\":[",
                st.submitted, st.rejected, st.completed, acc ? sum_wait / acc : 0, max_wait,
                acc ? sum_tat / acc : 0, makespan_ms, util, max_q, max_running, shutdown_t);
        for (int i = 0; i < w; i++) fprintf(o, "%s%ld", i ? "," : "", st.per_worker_completed[i]);
        fprintf(o, "]},\n\"verify\":{\"ok\":%s,\"checks\":[", all_ok ? "true" : "false");
        for (int i = 0; i < nc; i++) {
            fprintf(o, "%s\n{\"name\":\"%s\",\"ok\":%s,\"detail\":", i ? "," : "", checks[i].name,
                    checks[i].ok ? "true" : "false");
            json_str(o, checks[i].detail);
            fputc('}', o);
        }
        fprintf(o, "]}}\n");
        if (o != stdout) fclose(o);
    }

    free(sub); free(beg); free(fin); free(running_task); free(starts); free(ends);
    free(tasks); trace_free();
    return all_ok ? 0 : 4;
}
