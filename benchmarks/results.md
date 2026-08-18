| Fleet | Tasks/hour | Avg task (s) | Tick mean (ms) | Tick p95 (ms) | Budget used @6Hz | Max tick rate | Collisions | Guard stops |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 840 | 29.9 | 1.79 | 4.739 | 2.8% | 211.0 Hz | 0 | 0 |
| 25 | 2,117 | 23.8 | 5.914 | 18.611 | 11.2% | 53.7 Hz | 0 | 0 |
| 50 | 4,270 | 25.6 | 26.093 | 51.615 | 31.0% | 19.4 Hz | 0 | 1 |
| 75 | 6,463 | 26.8 | 14.291 | 22.956 | 13.8% | 43.6 Hz | 0 | 14 |
| 100 | 7,464 | 62.4 | 18.815 | 28.974 | 17.4% | 34.5 Hz | 0 | 648 |

_Measured on arm64 Darwin, Python 3.9.6, 1500 ticks per fleet size after 150 warmup ticks, grid 44x23._