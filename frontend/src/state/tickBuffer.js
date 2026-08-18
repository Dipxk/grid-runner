/**
 * Tick buffer + interpolation — the reason the demo looks fluid.
 *
 * The server ticks at 3–20 Hz. Rendering those positions directly would make
 * robots teleport one cell at a time. Instead we:
 *
 * 1. **Buffer** the last few snapshots (each is an authoritative grid state).
 * 2. **Rebuild an even timeline.** Snapshot arrival times jitter (network,
 *    GC, uneven tick compute), so instead of trusting `receivedAt` we place
 *    snapshot N at `base + (N - baseTick) * interval` and only re-base when
 *    drift exceeds a threshold. Playback therefore advances at a constant
 *    rate even though arrivals are uneven.
 * 3. **Render in the past** by `DELAY_TICKS` intervals. That deliberate lag
 *    means we almost always hold the snapshot *after* the one being rendered,
 *    which is what makes smooth corner interpolation possible.
 * 4. **Interpolate with centripetal Catmull–Rom** through four consecutive
 *    grid positions, so a robot turning a corner sweeps a rounded arc instead
 *    of hitting a hard 90° vertex. Straight runs stay perfectly linear, and
 *    stationary robots do not drift (duplicate control points fall back to
 *    linear interpolation).
 */

const isRemoteHost = typeof location !== 'undefined'
  && !['localhost', '127.0.0.1'].includes(location.hostname);

// Remote hosts (Render, etc.) need more buffer — WebSocket jitter is higher than localhost.
const DELAY_TICKS = isRemoteHost ? 3.2 : 2.05;
const MAX_SNAPSHOTS = isRemoteHost ? 12 : 8;
const REBASE_THRESHOLD_MS = isRemoteHost ? 720 : 420;

export class TickBuffer {
  constructor(intervalMs = 167) {
    this.intervalMs = intervalMs;
    this.snapshots = [];
    this.baseTick = null;
    this.baseTime = 0;
    this.latestTick = 0;
    this.paused = false;
  }

  setInterval(ms) {
    if (!ms || Math.abs(ms - this.intervalMs) < 0.5) return;
    this.intervalMs = ms;
    // Re-base on the newest snapshot so the new cadence starts cleanly.
    const newest = this.snapshots[this.snapshots.length - 1];
    if (newest) {
      this.baseTick = newest.tick;
      this.baseTime = performance.now();
      this.#retime();
    }
  }

  /** Ingest an authoritative snapshot. */
  push(snapshot) {
    const now = performance.now();
    const tick = snapshot.tick;

    if (this.baseTick === null) {
      this.baseTick = tick;
      this.baseTime = now;
    } else {
      const expected = this.baseTime + (tick - this.baseTick) * this.intervalMs;
      const drift = now - expected;
      if (Math.abs(drift) > REBASE_THRESHOLD_MS) {
        this.baseTick = tick;
        this.baseTime = now;
        this.#retime();
      }       else {
        // Nudge the clock so small persistent drift is absorbed invisibly.
        const nudge = isRemoteHost ? 0.035 : 0.02;
        this.baseTime += drift * nudge;
      }
    }

    const robots = new Map();
    for (const r of snapshot.robots) robots.set(r.id, r);

    this.snapshots.push({
      tick,
      robots,
      raw: snapshot,
      time: this.#timeFor(tick),
    });
    if (this.snapshots.length > MAX_SNAPSHOTS) this.snapshots.shift();
    this.latestTick = tick;
  }

  #timeFor(tick) {
    return this.baseTime + (tick - this.baseTick) * this.intervalMs;
  }

  #retime() {
    for (const s of this.snapshots) s.time = this.#timeFor(s.tick);
  }

  /** Newest authoritative snapshot (used for panels, metrics, jams). */
  latest() {
    return this.snapshots[this.snapshots.length - 1]?.raw ?? null;
  }

  /**
   * Interpolated view of the world for the current animation frame.
   * @param {number} now performance.now()
   * @returns {{robots: Array, tick: number, alpha: number}|null}
   */
  sample(now) {
    const snaps = this.snapshots;
    if (snaps.length === 0) return null;
    if (snaps.length === 1) {
      return { robots: this.#staticRobots(snaps[0]), tick: snaps[0].tick, alpha: 0 };
    }

    const renderTime = now - DELAY_TICKS * this.intervalMs;

    // Clamp to the ends of the buffer (start-up, pause, stalled connection).
    if (renderTime <= snaps[0].time) {
      return { robots: this.#staticRobots(snaps[0]), tick: snaps[0].tick, alpha: 0 };
    }
    const last = snaps[snaps.length - 1];
    if (renderTime >= last.time) {
      return { robots: this.#staticRobots(last), tick: last.tick, alpha: 1 };
    }

    let i = 0;
    for (let k = 0; k < snaps.length - 1; k++) {
      if (renderTime >= snaps[k].time && renderTime < snaps[k + 1].time) {
        i = k;
        break;
      }
    }

    const a = snaps[i];
    const b = snaps[i + 1];
    const span = Math.max(1, b.time - a.time);
    const t = Math.min(1, Math.max(0, (renderTime - a.time) / span));

    const p0 = snaps[i - 1] ?? a;
    const p3 = snaps[i + 2] ?? b;

    const robots = [];
    for (const [id, cur] of b.robots) {
      const prev = a.robots.get(id);
      if (!prev) {
        // Newly spawned robot: pop it in at its authoritative cell.
        robots.push({ ...cur, px: cur.x, py: cur.y, appear: 1 - t });
        continue;
      }
      const before = p0.robots.get(id) ?? prev;
      const after = p3.robots.get(id) ?? cur;
      const [px, py] = catmullRom(
        before.x, before.y,
        prev.x, prev.y,
        cur.x, cur.y,
        after.x, after.y,
        t,
      );
      robots.push({ ...cur, px, py, appear: 0 });
    }

    return { robots, tick: a.tick, alpha: t };
  }

  #staticRobots(snapshot) {
    const out = [];
    for (const [, r] of snapshot.robots) out.push({ ...r, px: r.x, py: r.y, appear: 0 });
    return out;
  }
}

/**
 * Centripetal Catmull–Rom interpolation between p1 and p2.
 *
 * Centripetal (alpha = 0.5) parameterisation is used rather than uniform
 * because uniform Catmull–Rom overshoots and forms cusps when control points
 * repeat — which happens constantly here, every time a robot waits a tick.
 * Degenerate spans fall back to a straight line.
 */
export function catmullRom(x0, y0, x1, y1, x2, y2, x3, y3, t) {
  if (x1 === x2 && y1 === y2) return [x1, y1];

  const d = (ax, ay, bx, by) => Math.pow(Math.hypot(bx - ax, by - ay), 0.5);
  const t0 = 0;
  const t1 = t0 + d(x0, y0, x1, y1);
  const t2 = t1 + d(x1, y1, x2, y2);
  const t3 = t2 + d(x2, y2, x3, y3);

  // Repeated control points collapse the knot spacing — use linear instead.
  if (!(t1 > t0) || !(t2 > t1) || !(t3 > t2)) {
    return [x1 + (x2 - x1) * t, y1 + (y2 - y1) * t];
  }

  const tt = t1 + (t2 - t1) * t;
  const a1x = ((t1 - tt) * x0 + (tt - t0) * x1) / (t1 - t0);
  const a1y = ((t1 - tt) * y0 + (tt - t0) * y1) / (t1 - t0);
  const a2x = ((t2 - tt) * x1 + (tt - t1) * x2) / (t2 - t1);
  const a2y = ((t2 - tt) * y1 + (tt - t1) * y2) / (t2 - t1);
  const a3x = ((t3 - tt) * x2 + (tt - t2) * x3) / (t3 - t2);
  const a3y = ((t3 - tt) * y2 + (tt - t2) * y3) / (t3 - t2);

  const b1x = ((t2 - tt) * a1x + (tt - t0) * a2x) / (t2 - t0);
  const b1y = ((t2 - tt) * a1y + (tt - t0) * a2y) / (t2 - t0);
  const b2x = ((t3 - tt) * a2x + (tt - t1) * a3x) / (t3 - t1);
  const b2y = ((t3 - tt) * a2y + (tt - t1) * a3y) / (t3 - t1);

  return [
    ((t2 - tt) * b1x + (tt - t1) * b2x) / (t2 - t1),
    ((t2 - tt) * b1y + (tt - t1) * b2y) / (t2 - t1),
  ];
}
