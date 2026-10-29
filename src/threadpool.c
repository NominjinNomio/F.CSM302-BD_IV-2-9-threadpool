/*
 * threadpool.c — Pthreads + POSIX mutex + semaphore ашигласан thread pool.
 *
 * Номын (OSC Ch.7, Project 1) шаардлагын харгалзаа:
 *   1. pool_init()      — worker thread-үүдийг үүсгэж, mutex, semaphore-ийг эхлүүлнэ.
 *   2. pool_submit()    — task-ийг struct болгон enqueue() хийнэ; queue массив тул
 *                          дүүрсэн үед 1 буцаана.
 *   3. worker()         — semaphore дээр хүлээж, ажил ирэхэд dequeue() хийн execute().
 *   4. mutex            — queue-ийн хандалтыг race condition-оос хамгаална.
 *   5. pool_shutdown()  — бүх task дууссаны дараа worker-уудыг зогсоож pthread_join().
 *
 * Shutdown-ы хувьд номонд pthread_cancel()-ийг дурдсан. Гэвч task ажиллаж байх үед
 * цуцлах нь task-ийг дутуу орхих эрсдэлтэй, мөн "бүх task дууссаны дараа" гэсэн
 * шаардлагатай зөрчилдөнө. Тиймээс shutdown флаг + semaphore-ийг worker бүрт нэг
 * удаа post хийх аргыг сонгосон (тайлангийн 5-р хэсэгт тайлбарласан).
 */
#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE   /* dispatch_semaphore, clock_gettime */
#endif
#include "threadpool.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ---------------- Semaphore wrapper -------------------------------------------
 * Linux дээр POSIX unnamed semaphore (sem_init). macOS unnamed semaphore-ийг
 * дэмждэггүй тул тэнд GCD-ийн dispatch_semaphore-ийг ижил утгаар ашиглана.   */
#ifdef __APPLE__
#include <dispatch/dispatch.h>
typedef dispatch_semaphore_t psem_t;
static int  psem_init(psem_t *s, unsigned v) { *s = dispatch_semaphore_create(v); return *s ? 0 : -1; }
static void psem_wait(psem_t *s) { dispatch_semaphore_wait(*s, DISPATCH_TIME_FOREVER); }
static void psem_post(psem_t *s) { dispatch_semaphore_signal(*s); }
static void psem_destroy(psem_t *s) { (void)s; }
#else
#include <semaphore.h>
#include <errno.h>
typedef sem_t psem_t;
static int  psem_init(psem_t *s, unsigned v) { return sem_init(s, 0, v); }
static void psem_wait(psem_t *s) { while (sem_wait(s) == -1 && errno == EINTR) { } }
static void psem_post(psem_t *s) { sem_post(s); }
static void psem_destroy(psem_t *s) { sem_destroy(s); }
#endif

/* ---------------- Task ба queue -------------------------------------------- */
typedef struct {
    void (*function)(void *p);
    void *data;
    int   id;
} task;

typedef struct {
    int id;
    pthread_t tid;
} worker_info;

static task          *queue;          /* тойрог массив (circular queue) */
static int            qcap, qhead, qtail, qcount;
static pthread_mutex_t qmutex = PTHREAD_MUTEX_INITIALIZER;
static psem_t          work_available; /* queue дахь task-ийн тоог тоолно */

static worker_info    workers[POOL_MAX_THREADS];
static int            nthreads;
static int            initialized, shutting_down;
static int            next_auto_id;

static long submitted, rejected, completed;
static long per_worker_completed[POOL_MAX_THREADS];

/* ---------------- Trace ---------------------------------------------------- */
static pool_event     *tr_buf;
static size_t          tr_cap, tr_len;
static long            tr_dropped;
static pthread_mutex_t tr_mutex = PTHREAD_MUTEX_INITIALIZER;
static struct timespec t0;
static int             t0_set;

long long trace_now_us(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)(now.tv_sec - t0.tv_sec) * 1000000LL +
           (now.tv_nsec - t0.tv_nsec) / 1000;
}

/* Цагийг mutex дотор авдаг тул массив дахь үйл явдлууд хугацааны дарааллаар байна. */
static void trace(pool_event_type type, int worker, int taskid, int qlen)
{
    if (!tr_buf) return;
    pthread_mutex_lock(&tr_mutex);
    if (tr_len < tr_cap) {
        pool_event *e = &tr_buf[tr_len++];
        e->t_us = trace_now_us();
        e->type = type; e->worker = worker; e->task = taskid; e->qlen = qlen;
    } else {
        tr_dropped++;
    }
    pthread_mutex_unlock(&tr_mutex);
}

int trace_enable(size_t capacity)
{
    if (capacity == 0) return -1;
    free(tr_buf);
    tr_buf = calloc(capacity, sizeof *tr_buf);
    if (!tr_buf) return -1;
    tr_cap = capacity; tr_len = 0; tr_dropped = 0;
    return 0;
}

const pool_event *trace_events(size_t *count)
{
    if (count) *count = tr_len;
    return tr_buf;
}

void trace_free(void) { free(tr_buf); tr_buf = NULL; tr_cap = tr_len = 0; }

const char *trace_type_name(pool_event_type t)
{
    static const char *names[] = { "POOL_INIT", "IDLE", "SUBMIT", "REJECT",
                                   "START", "END", "SHUTDOWN", "WORKER_EXIT" };
    return (t >= 0 && t <= EV_WORKER_EXIT) ? names[t] : "?";
}

/* ---------------- Queue (qmutex барьсан үед л дуудна) --------------------- */
static int enqueue(task t)
{
    if (qcount == qcap) return 1;
    queue[qtail] = t;
    qtail = (qtail + 1) % qcap;
    qcount++;
    return 0;
}

static task dequeue(void)
{
    task t = queue[qhead];
    qhead = (qhead + 1) % qcap;
    qcount--;
    return t;
}

static void execute(void (*somefunction)(void *p), void *p) { (*somefunction)(p); }

/* ---------------- Worker --------------------------------------------------- */
static void *worker(void *param)
{
    worker_info *me = param;

    for (;;) {
        trace(EV_WORKER_IDLE, me->id, -1, -1);
        psem_wait(&work_available);           /* ажил (эсвэл shutdown) хүлээнэ */

        pthread_mutex_lock(&qmutex);
        if (qcount == 0 && shutting_down) {   /* queue хоосон + shutdown → гарна */
            pthread_mutex_unlock(&qmutex);
            break;
        }
        task t = dequeue();
        trace(EV_START, me->id, t.id, qcount);
        pthread_mutex_unlock(&qmutex);

        execute(t.function, t.data);          /* critical section-оос ГАДНА */

        pthread_mutex_lock(&qmutex);
        completed++;
        per_worker_completed[me->id]++;
        trace(EV_END, me->id, t.id, qcount);
        pthread_mutex_unlock(&qmutex);
    }

    trace(EV_WORKER_EXIT, me->id, -1, -1);
    return NULL;
}

/* ---------------- API ------------------------------------------------------ */
int pool_init_ex(int n, int cap)
{
    if (n < 1 || n > POOL_MAX_THREADS || cap < 1 || cap > POOL_MAX_QUEUE) return -1;

    pthread_mutex_lock(&qmutex);
    if (initialized) { pthread_mutex_unlock(&qmutex); return -1; }

    queue = calloc((size_t)cap, sizeof *queue);
    if (!queue) { pthread_mutex_unlock(&qmutex); return -1; }
    qcap = cap; qhead = qtail = qcount = 0;
    nthreads = n; shutting_down = 0; next_auto_id = 0;
    submitted = rejected = completed = 0;
    memset(per_worker_completed, 0, sizeof per_worker_completed);
    if (psem_init(&work_available, 0) != 0) {
        free(queue); queue = NULL;
        pthread_mutex_unlock(&qmutex);
        return -1;
    }
    clock_gettime(CLOCK_MONOTONIC, &t0); t0_set = 1;
    initialized = 1;
    trace(EV_POOL_INIT, n, cap, 0);   /* worker талбарт thread-ийн тоо, task-д багтаамж */
    pthread_mutex_unlock(&qmutex);

    for (int i = 0; i < n; i++) {
        workers[i].id = i;
        if (pthread_create(&workers[i].tid, NULL, worker, &workers[i]) != 0) {
            fprintf(stderr, "pool_init: pthread_create амжилтгүй (worker %d)\n", i);
            /* үүссэн worker-уудыг зөв зогсооно */
            pthread_mutex_lock(&qmutex);
            shutting_down = 1;
            pthread_mutex_unlock(&qmutex);
            for (int j = 0; j < i; j++) psem_post(&work_available);
            for (int j = 0; j < i; j++) pthread_join(workers[j].tid, NULL);
            psem_destroy(&work_available);
            free(queue); queue = NULL; initialized = 0;
            return -1;
        }
    }
    return 0;
}

void pool_init(void)
{
    if (pool_init_ex(NUMBER_OF_THREADS, QUEUE_SIZE) != 0)
        fprintf(stderr, "pool_init: эхлүүлж чадсангүй\n");
}

int pool_submit_id(void (*somefunction)(void *p), void *p, int task_id)
{
    if (!somefunction) return POOL_ERR;

    pthread_mutex_lock(&qmutex);
    if (!initialized || shutting_down) { pthread_mutex_unlock(&qmutex); return POOL_ERR; }
    if (task_id < 0) task_id = next_auto_id++;

    task t = { somefunction, p, task_id };
    if (enqueue(t) != 0) {
        rejected++;
        trace(EV_REJECT, -1, task_id, qcount);
        pthread_mutex_unlock(&qmutex);
        return POOL_FULL;
    }
    submitted++;
    trace(EV_SUBMIT, -1, task_id, qcount);
    pthread_mutex_unlock(&qmutex);

    psem_post(&work_available);   /* хүлээж буй нэг worker-ийг сэрээнэ */
    return POOL_OK;
}

int pool_submit(void (*somefunction)(void *p), void *p)
{
    return pool_submit_id(somefunction, p, -1);
}

int pool_queue_length(void)
{
    pthread_mutex_lock(&qmutex);
    int n = qcount;
    pthread_mutex_unlock(&qmutex);
    return n;
}

void pool_shutdown(void)
{
    pthread_mutex_lock(&qmutex);
    if (!initialized || shutting_down) { pthread_mutex_unlock(&qmutex); return; }
    shutting_down = 1;
    trace(EV_SHUTDOWN, -1, -1, qcount);
    pthread_mutex_unlock(&qmutex);

    /* Worker бүрт нэг "гарах" дохио. Queue-д үлдсэн task бүр өөрийн post-той тул
     * worker-ууд эхлээд бүх task-ийг гүйцээж, дараа нь л гарна. */
    for (int i = 0; i < nthreads; i++) psem_post(&work_available);
    for (int i = 0; i < nthreads; i++) pthread_join(workers[i].tid, NULL);

    pthread_mutex_lock(&qmutex);
    psem_destroy(&work_available);
    free(queue); queue = NULL;
    initialized = 0;
    pthread_mutex_unlock(&qmutex);
}

void pool_get_stats(pool_stats *out)
{
    pthread_mutex_lock(&qmutex);
    memset(out, 0, sizeof *out);
    out->nthreads = nthreads; out->qcap = qcap;
    out->submitted = submitted; out->rejected = rejected; out->completed = completed;
    memcpy(out->per_worker_completed, per_worker_completed, sizeof per_worker_completed);
    pthread_mutex_unlock(&qmutex);
}
