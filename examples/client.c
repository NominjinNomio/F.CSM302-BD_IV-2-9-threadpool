/*
 * client.c — номын source-code download дахь client.c-тэй ижил санаатай жишээ.
 * Номын API-г (pool_init, pool_submit, pool_shutdown) өөрчлөлтгүй ашиглана.
 * Хоёр тооны нийлбэрийг thread pool-ийн worker дээр бодуулна.
 */
#include <stdio.h>
#include <unistd.h>
#include "../src/threadpool.h"

struct data {
    int a;
    int b;
};

static void add(void *param)
{
    struct data *temp = (struct data *)param;
    printf("I add two values %d and %d result = %d\n", temp->a, temp->b, temp->a + temp->b);
}

int main(void)
{
    struct data work[5] = { {5, 10}, {1, 2}, {100, 200}, {-7, 7}, {40, 2} };

    pool_init();                                 /* 3 worker, queue 10 */
    for (int i = 0; i < 5; i++)
        if (pool_submit(&add, &work[i]) != 0)
            fprintf(stderr, "task %d submit амжилтгүй\n", i);

    pool_shutdown();                             /* бүх task дууссаны дараа зогсоно */
    return 0;
}
