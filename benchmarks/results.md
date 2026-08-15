| Fleet | Tasks/hour | Avg task (s) | Tick mean (ms) | Tick p95 (ms) | Budget used @6Hz | Max tick rate | Collisions | Guard stops |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 840 | 29.9 | 2.009 | 5.268 | 3.2% | 189.8 Hz | 0 | 0 |
| 25 | 2,117 | 23.8 | 4.576 | 9.099 | 5.5% | 109.9 Hz | 0 | 0 |
| 50 | 4,270 | 25.6 | 9.055 | 15.329 | 9.2% | 65.2 Hz | 0 | 1 |
| 75 | 6,463 | 26.8 | 15.588 | 23.318 | 14.0% | 42.9 Hz | 0 | 14 |
| 100 | 7,464 | 62.4 | 20.471 | 29.251 | 17.6% | 34.2 Hz | 0 | 648 |

_Measured on arm64 Darwin, Python 3.9.6, 1500 ticks per fleet size after 150 warmup ticks, grid 44x23._