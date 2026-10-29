/*
 * threadpool.h — F.CSM302 БД1, IV-2-9 "Designing a Thread Pool"
 *
 * Operating System Concepts (10th ed.), Chapter 7, Programming Project 1 (POSIX).
 * Номын API (pool_init / pool_submit / pool_shutdown)-г яг хэвээр нь хадгалж,
 * worker-ийн тоо болон queue-ийн багтаамжийг ажиллах үед тохируулах
 * pool_init_ex()-ийг нэмсэн.
 */
#ifndef THREADPOOL_H
#define THREADPOOL_H

#include <stddef.h>

/* Номын анхдагч утгууд (source-code download дахь threadpool.c-тэй ижил) */
#define NUMBER_OF_THREADS 3
#define QUEUE_SIZE        10

/* Хязгаар — оролтын шалгалтад ашиглана */
#define POOL_MAX_THREADS  64
#define POOL_MAX_QUEUE    4096

/* pool_submit()-ийн буцаах утга (номын дагуу: 0 амжилттай, 1 амжилтгүй) */
#define POOL_OK        0
#define POOL_FULL      1   /* queue дүүрсэн тул task-ийг хүлээж аваагүй      */
#define POOL_ERR       2   /* pool эхлээгүй / shutdown хийгдсэн / буруу аргумент */

/* ---- Номын API ---------------------------------------------------------- */
void pool_init(void);                                   /* 3 worker, queue 10 */
int  pool_submit(void (*somefunction)(void *p), void *p);
void pool_shutdown(void);

/* ---- Өргөтгөл ----------------------------------------------------------- */
/* nthreads ∈ [1, POOL_MAX_THREADS], qcap ∈ [1, POOL_MAX_QUEUE]. 0 = амжилттай */
int  pool_init_ex(int nthreads, int qcap);

/* Task-д хүний уншихуйц дугаар оноож submit хийх (trace/UI-д ашиглана). */
int  pool_submit_id(void (*somefunction)(void *p), void *p, int task_id);

/* Одоогийн queue-ийн урт (mutex дор уншина) */
int  pool_queue_length(void);

/* ---- Trace (UI дүрслэлд зориулсан үйл явдлын бүртгэл) --------------------- */
typedef enum {
    EV_POOL_INIT = 0, /* pool үүссэн                          */
    EV_WORKER_IDLE,   /* worker ажил хүлээж эхэлсэн (sem_wait) */
    EV_SUBMIT,        /* task queue-д орсон                   */
    EV_REJECT,        /* queue дүүрсэн тул татгалзсан          */
    EV_START,         /* worker task-ийг queue-ээс авч эхлүүлсэн */
    EV_END,           /* task дууссан                         */
    EV_SHUTDOWN,      /* pool_shutdown() дуудагдсан            */
    EV_WORKER_EXIT    /* worker thread дууссан                 */
} pool_event_type;

typedef struct {
    long long        t_us;    /* pool_init-ээс хойших хугацаа, микросекунд */
    pool_event_type  type;
    int              worker;  /* -1 бол хамааралгүй */
    int              task;    /* -1 бол хамааралгүй */
    int              qlen;    /* үйл явдлын дараах queue-ийн урт */
} pool_event;

/* Бүртгэлийг асаах (pool_init-ээс өмнө дуудна). capacity — хамгийн их үйл явдал. */
int  trace_enable(size_t capacity);
const pool_event *trace_events(size_t *count);
const char *trace_type_name(pool_event_type t);
long long   trace_now_us(void);
void trace_free(void);

/* Тоолуурууд (shutdown-ы дараа уншина) */
typedef struct {
    int nthreads, qcap;
    long submitted, rejected, completed;
    long per_worker_completed[POOL_MAX_THREADS];
} pool_stats;
void pool_get_stats(pool_stats *out);

#endif
