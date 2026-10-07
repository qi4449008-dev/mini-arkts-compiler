/* micro-benchmark: 512x512 matrix multiply, cache-friendly i-k-j order */
#include <stdio.h>
#include <time.h>
#define N 512
static double A[N][N], B[N][N], C[N][N];

int main(void) {
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            A[i][j] = i + j * 0.5;
            B[i][j] = i - j * 0.25;
        }
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (int i = 0; i < N; i++)
        for (int k = 0; k < N; k++) {
            double a = A[i][k];
            for (int j = 0; j < N; j++)
                C[i][j] += a * B[k][j];
        }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double ms = (t1.tv_sec - t0.tv_sec) * 1000.0
              + (t1.tv_nsec - t0.tv_nsec) / 1e6;
    double s = 0;
    for (int i = 0; i < N; i++) s += C[0][i];
    printf("time=%.1fms checksum=%.1f\n", ms, s);
    return 0;
}
