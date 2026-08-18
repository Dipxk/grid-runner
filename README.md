# Grid Runner

A live warehouse operations console for a robot fleet. You place orders, jam
aisles, and run a Black Friday peak; the fleet plans **conflict-free routes
through a space-time reservation table** and the floor stays at zero collisions.

Open it, and you run a shift — not a pathfinding demo.

**Live demo:** https://grid-runner-vnj2.onrender.com  
(Free Render host — first load after idle can take ~30–60s.)

## Quick start

```bash
make setup     # creates ./gr-env and installs dependencies
make run       # http://localhost:8000
```

Or with Docker:

```bash
docker compose up --build   # http://localhost:8000
```

Hard-refresh the tab if you already had it open (`Cmd+Shift+R`).

### What to click

1. **You dispatch (D)** — pause random demand. Robots finish in-flight work, then wait.
2. **Order (O)** — click a **pick slot**, then a **dock door**. That tote jumps the queue; the pick LED and dock lamp light immediately.
3. **Jam (J)** — click an aisle. The fleet replans around it.
4. **Black Friday (G)** — timed peak: 32 robots, seeded aisle jams, a score.
5. Click a robot to follow its path. **Space** pauses.

Rush (R) still drops a high-priority pick with a random door. Task burst (B) dumps extra random work. Live demand turns the firehose back on.

Dock lamps: **green** = idle, **red** = a robot is carrying to that door. Orange stripes are jams, not dock errors.

| Command | What it does |
| --- | --- |
| `make test` | Full suite, including 12 randomised collision scenarios |
| `make test-fast` | Same minus the slow randomised sweep |
| `make bench` | Load test → `benchmarks/results.{json,md}` |

---

## What you're looking at

The canvas is a 2.5D warehouse on the existing 2D sim (no Three.js rewrite).
Hit-testing stays grid-based: rack extrusion never leaves a shelf cell, so
aisles stay clickable.

- **Racks** — extruded bays with carton inventory and aisle tape (`AISLE A`)
- **Pick slots** — put-to-light bezels; the LED pulses when a robot is inbound
- **Dock doors** — `DOOR 01` frames with occupancy lamps
- **OPS ticker** — picks, dock-outs, jams, rush/authored orders

The left rail is ops copy (picks / hour, orders out), not algorithm debug.

---

## How it is put together

```
┌──────────────────────────────────────────────────────────────────────────┐
│  BROWSER  (vanilla ES modules + Canvas 2D, no build step)                │
│                                                                          │
│   net/socket.js ──▶ state/tickBuffer.js ──▶ render/floor.js  (cached)    │
│    reconnecting     even-timeline rebase      render/scene.js (per frame)│
│    WebSocket        + Catmull-Rom interp   ──▶ ui/{metrics,inspector,    │
│                     (renders ~2 ticks back)      controls,ticker,        │
│                                                  scenario}.js            │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │  WebSocket /ws
     tick snapshots ▼           │  ▲ pause / speed / jam / order / demand /
                                │    rush / burst / fleet / scenario
┌───────────────────────────────┴──────────────────────────────────────────┐
│  FastAPI + uvicorn (asyncio)                                             │
│                                                                          │
│   SimulationRunner ── drift-corrected tick clock                         │
│      └─ ClientChannel (bounded queue per client, drops stale snapshots)  │
│                                                                          │
│   SimulationEngine.step()                                                │
│      1. expire jams        → world.py    (procedural floor plan)         │
│      2. spawn tasks        → models.py   (off in "You dispatch")         │
│      3. allocate           → allocator.py (nearest-idle + age + density) │
│      4. plan               → pathfinding.py (windowed space-time A*)     │
│                              reservation.py (vertex + edge reservations) │
│      5. execute            → execution guard (independent safety layer)  │
│      6. verify             → runtime collision assertion (stays 0)       │
│      7. metrics            → metrics.py (rolling, simulated-time based)  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Measured results

All numbers below were produced by `backend/scripts/benchmark.py` on this
machine. Nothing is estimated; re-run `make bench` to reproduce.

**Machine:** arm64 Darwin, Python 3.9.6 · **Floor:** 44×23 grid, 732 walkable
cells, 70 pick faces, 4 dropoff stations · **Method:** 1,500 measured ticks per
fleet size after 150 warmup ticks.

| Fleet | Tasks/hour | Avg task (s) | Tick mean (ms) | Tick p95 (ms) | Budget used @6 Hz | Max tick rate | Collisions | Guard stops |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 840 | 34.8 | 2.01 | 5.27 | 3.2% | 190 Hz | 0 | 0 |
| 25 | 2,117 | 39.4 | 4.58 | 9.10 | 5.5% | 110 Hz | 0 | 0 |
| 50 | 4,270 | 44.4 | 9.06 | 15.33 | 9.2% | 65 Hz | 0 | 1 |
| 75 | 6,463 | 48.7 | 15.59 | 23.32 | 14.0% | 43 Hz | 0 | 14 |
| **100** | **7,464** | 60.7 | 20.47 | 29.25 | 17.5% | 34 Hz | 0 | 648 |

### How to read that

* **Throughput scales roughly linearly to 100 robots** — 840 → 7,464 tasks/h for
  a 10× fleet, with per-task latency rising only 35 s → 61 s as the aisles fill.
* **Python is not the bottleneck at demo scale.** At the default 18-robot demo a
  tick costs ~4 ms against a 167 ms budget (6 Hz), about 2.5% of the available
  time. Even 100 robots sustain ~34 ticks/s, 5.7× the demo rate.
* **Congestion shows up as guard stops, not crashes.** Guard interventions climb
  from 0 to 648 over 1,500 ticks at 100 robots: robots yield to each other more
  often, throughput keeps rising, and collisions stay at 0.

An earlier build peaked at ~50 robots and then *collapsed* (197 tasks/h at 75
robots, with the execution guard firing 24×/tick). The cause was a station
funnel: every task is born with a fixed dropoff, so loaded robots piled onto one
bay, the ones that could not reserve the goal cell stalled on the approach, and
the stalled bodies blocked the robots that could have delivered. Two changes
removed it — loaded robots re-pick their bay each tick by *distance + inbound
traffic*, and any robot standing still with no legal plan for 6 ticks may step
aside into a free neighbour to unwind the knot. Same floor, same guard: 75
robots went 197 → 6,463 tasks/h. Both are covered by regression tests in
`test_engine_integration.py`.
* **Animation smoothness is decoupled from tick rate.** The client renders at
  60 fps regardless, interpolating between ticks — so a 6 Hz simulation still
  looks fluid. Choppiness would only appear if tick compute exceeded the tick
  interval, which needs a fleet far beyond what the floor can absorb.

### Where the time actually goes

Per-tick cost is dominated by windowed A* replanning, which scales roughly
linearly in fleet size (0.20 ms/robot mean at 100 robots). Allocation is capped
to the head of the task backlog, so a deep queue does not inflate tick cost —
an earlier version scanned the whole backlog and tick time grew from 4 ms to
20 ms as the queue built up.

---

## Collision avoidance: exactly what is guaranteed

This distinction matters more than the numbers, and the code is structured so
the two claims stay separable.

**1. Guaranteed by construction — conflict-free *plans*.**
`ReservationTable` stores two kinds of reservation:

* *vertex* `(x, y, t)` — robot R occupies this cell at this tick;
* *edge* `(u→v, t)` — robot R traverses this edge arriving at this tick.

`commit_path()` refuses to write over an existing reservation, and the planner
only expands successors whose vertex **and** reverse edge are free. Edge
reservations are what block head-on swaps: two robots exchanging cells never
share a cell at any tick, yet would pass through each other. So *any* set of
plans committed through this table is pairwise conflict-free for every tick it
covers. That is a property of the data structure, verified in
`test_reservation.py` and `test_pathfinding.py`.

**2. Guaranteed by construction — conflict-free *executed transitions*.**
Plans can go stale between ticks (a robot may fail to find any legal window and
hold position without reservations). So execution is filtered by an independent
**execution guard** that re-validates the actual move set against live robot
positions each tick: no two robots may claim one cell, no swaps, and no robot
may enter a cell whose occupant is staying — applied to a fixpoint so that
rejections cascade correctly, while cyclic rotations (A→B→C→A) still flow.

**3. Empirical, not proven — zero collisions in tested scenarios.**
A runtime verifier asserts the invariant after every tick and its counter is
displayed live in the UI. Across the test suite (12 randomised scenarios with
random grids, fleet sizes 6–22, jam storms, task bursts and mid-run fleet
resizes, plus a deliberately congested 20-robots-in-a-tiny-aisle case) and the
full benchmark sweep up to 100 robots, the count is **0**.

**What I do not claim:** the system is not proven deadlock-free, and there is no
formal proof that a plan always exists. Three heuristics keep traffic moving in
practice — a priority boost for long-blocked robots, dropoff rebalancing away
from congested bays, and a step-aside move for robots stuck 6+ ticks with no
legal plan — but they are mitigations, not a proof. Under extreme congestion the
fleet slows down and yields more; it does not crash into itself.

> Honest one-liner: *"collision-free by construction at both the planning and
> execution layers; zero collisions observed across randomised tests and
> benchmarks — not a formal proof of deadlock freedom."*

---

## How the smooth motion works

The simulation is discrete (6 ticks/s by default) but the animation is not.

1. **Buffer** the last 8 snapshots client-side.
2. **Rebuild an even timeline.** Arrival times jitter, so snapshot *N* is placed
   at `base + (N − baseTick) × interval` rather than at its arrival time; small
   drift is absorbed by nudging `base`, large drift triggers a re-base. Playback
   advances at a constant rate even when the network does not.
3. **Render ~2 ticks in the past.** That deliberate lag means the snapshot
   *after* the one being drawn is almost always available.
4. **Interpolate with centripetal Catmull–Rom** through four consecutive grid
   positions, so a robot turning a corner sweeps a rounded arc instead of
   hitting a 90° vertex. Centripetal (α = 0.5) parameterisation is used because
   uniform Catmull–Rom overshoots and forms cusps when control points repeat —
   which happens every time a robot waits a tick. Degenerate spans fall back to
   linear.

Chassis rotation is smoothed separately toward the direction of travel, so
robots visibly turn rather than snapping their heading.

---

## Design decisions worth defending

**Windowed planning (WHCA*-style), not full-horizon MAPF.** Reservations cover
`[now, now + 10]` ticks and every plan is padded with waits to fill the window,
so coverage is gap-free. Robots replan when their runway is a third consumed,
when a jam lands on their path, or when their goal changes — which staggers
replanning across ticks instead of recomputing the whole fleet every tick.

**Priority ordering with a blocked-time boost.** Carrying robots plan first
(they hold inventory), then robots that have been blocked longest. Deterministic
ordering keeps runs reproducible; the boost is a cheap anti-livelock measure.

**Dropoff bays are chosen late, not at task creation.** A loaded robot re-picks
its station every tick by `distance + 4 × robots already inbound`, with
hysteresis so it never dithers and never switches within two cells of the bay.
Committing early is what created the funnel that deadlocked dense fleets.

**Demand is throttled by queue depth.** Ambient task spawn scales with fleet
size, but stops while the backlog exceeds a quarter of the fleet. Without the
ceiling a small surplus compounds into a queue that only inflates avg task time
with waiting, not driving. Operator bursts bypass it — a spike should be felt.
**You dispatch** turns ambient spawn off entirely so the floor only moves on
orders you place.

**Snapshots, not deltas.** A 20-robot tick payload is a few KB. Deltas would buy
little and cost a lot of bug surface — and any dropped frame self-heals.

**Bounded per-client send queues.** A single stalled browser tab must never
stall the simulation. Each client gets a depth-2 queue drained by its own task;
slow clients drop stale snapshots instead of applying backpressure to the tick
loop. (This was a real bug found during development: one backgrounded tab froze
the whole simulation.)

**No frontend build step.** Plain ES modules split into `net/`, `state/`,
`render/` and `ui/`. The demo is one command, the Docker image is small, and the
code is still modular — a bundler would add tooling without improving the
result at this size.

**Stay 2.5D on Canvas, not a Three.js rewrite.** Racks are extruded inside their
own cells so the interpolator, hit-testing, and reservation grid stay the same
code path. Full 3D would throw away the part that already looks expensive.

---

## Project layout

```
backend/
  app/
    config.py        SimConfig + GRIDRUNNER_* env overrides
    world.py         procedural floor plan, jam overlay
    reservation.py   space-time reservation table  ← correctness core
    pathfinding.py   windowed space-time A*
    allocator.py     greedy nearest-idle + age boost + density penalty
    models.py        Robot / Task
    metrics.py       rolling throughput, latency, tick compute
    engine.py        tick pipeline, execution guard, runtime verifier
    server.py        FastAPI, WebSocket hub, static hosting
  scripts/benchmark.py
  tests/
frontend/
  index.html  styles.css
  src/
    main.js          render loop + wiring only
    net/socket.js    reconnecting WebSocket
    state/tickBuffer.js  interpolation  ← animation core
    render/{camera,floor,scene}.js
    ui/{metrics,inspector,controls,toasts,ticker,scenario}.js
    audio/sound.js
benchmarks/results.{json,md}
```

---

## Resume bullet (measured, not estimated)

> Built **Grid Runner**, a warehouse fleet ops console in Python
> (FastAPI/asyncio) with a 60 fps Canvas frontend: space-time reservation-table
> planning (vertex + edge reservations) makes robot plans and executed moves
> conflict-free by construction, with **zero collisions across randomised test
> scenarios and a 10–100 robot benchmark sweep**. Sustains **7,464 tasks/hour at
> 100 robots** with **20 ms mean tick compute (p95 29 ms) against a 167 ms
> budget**, and diagnosed a dropoff-station deadlock from benchmark data —
> congestion-aware bay selection plus a step-aside recovery move took a 75-robot
> fleet from **197 to 6,463 tasks/hour** with collisions still at zero.
> Operators can pause random demand and place pick→dock orders on the live floor.

---

## Next

The floor is a showable demo. The systems claim that is still missing:

* **Dumb twin** — split-screen, same floor / tasks / jams. Left = reservation
  planner (0 collisions). Right = independent A*. That is the comparison a
  sharp interviewer will ask for.

Not next: Three.js, paid hosting, more scenarios, accounts.
