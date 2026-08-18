# Planner comparison — WHCA* vs baseline

## Methodology

Identical seeded scenarios; shared allocator, horizon, replan triggers, demand model, execution guard, warmup, and measurement window.

| Held constant | Value |
| --- | --- |
| Seed | 17 |
| Warmup ticks | 60 |
| Measured ticks | 600 |
| Horizon | 10 |
| Demand | fleet × 0.024 tasks/tick |

| Differs | WHCA* | Baseline |
| --- | --- | --- |
| Planner | space-time A* + reservations | spatial A*, no reservations |
| Conflict handling | reserved windows | execution guard at runtime |

| Planner | Fleet | Tasks/h | Avg task (s) | Tick mean | Tick p95 | Guard | Blocked | Replans | Failed | Collisions | Avg route | Dist/task |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| whca | 16 | 1,422 | 27.6 | 3.007 | 6.246 | 0 | 0 | 1936 | 0 | 0 | 102.38 | 34.73 |
| baseline | 16 | 54 | 110.6 | 1.646 | 2.223 | 8329 | 8329 | 8596 | 0 | 0 | 14.59 | 29.67 |
| whca | 32 | 2,730 | 25.5 | 5.563 | 10.249 | 0 | 0 | 3895 | 0 | 0 | 203.51 | 33.65 |
| baseline | 32 | 102 | 96.4 | 2.511 | 3.145 | 16606 | 16602 | 17142 | 0 | 0 | 29.8 | 31.53 |

_Measured on arm64 Darwin, Python 3.9.6, grid 44x23._
