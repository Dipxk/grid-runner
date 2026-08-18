# Planner comparison — WHCA* vs baseline

Controlled comparison on identical seeds. **WHCA*** uses vertex + edge space-time reservations; **baseline** uses independent spatial A* with execution-guard conflict resolution only.

| Planner | Fleet | Tasks/hour | Avg task (s) | Tick mean (ms) | Tick p95 (ms) | Guard stops | Blocked ticks | Replans | Collisions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| whca | 16 | 1,422 | 27.6 | 3.214 | 6.718 | 0 | 0 | 1936 | 0 |
| baseline | 16 | 0 | 24.4 | 11.757 | 12.357 | 9600 | 9600 | 9600 | 0 |
| whca | 32 | 2,730 | 25.5 | 5.714 | 10.502 | 0 | 0 | 3895 | 0 |
| baseline | 32 | 6 | 26.0 | 30.738 | 32.039 | 19178 | 19177 | 19200 | 0 |

_Measured on arm64 Darwin, Python 3.9.6, 600 ticks per run after 60 warmup ticks, seed 17, grid 44x23._
