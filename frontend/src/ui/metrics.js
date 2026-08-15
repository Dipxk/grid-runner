/**
 * Metrics panel.
 *
 * Numbers are *tweened* on the animation frame rather than assigned on tick
 * arrival: a value that jumps 812 -> 947 every 167ms reads as flicker, while
 * an exponentially-smoothed counter reads as a live instrument. The tween is
 * frame-rate independent and snaps once it is within half a display unit so
 * counters still land on exact integers.
 */

const SMOOTHING = 0.12;

export class MetricsPanel {
  constructor(root = document) {
    this.fields = new Map();
    for (const el of root.querySelectorAll('[data-metric]')) {
      this.fields.set(el, { el, key: el.dataset.metric, current: 0, target: 0, decimals: decimalsFor(el.dataset.metric) });
    }
    this.fleetSuffix = root.querySelector('[data-metric-raw="fleetSize"]');
    this.budgetEl = root.querySelector('[data-raw="budget"]');
    this.computeFill = root.querySelector('#compute-fill');
    this.collisionBadge = root.querySelector('#collision-badge');
    this.tickValue = root.querySelector('#tick-value');
    this.spark = new Sparkline(root.querySelector('#spark'));
    this.budgetMs = 167;
    this.lastMetrics = null;
  }

  setBudget(ms) {
    this.budgetMs = ms;
    if (this.budgetEl) this.budgetEl.textContent = Math.round(ms);
  }

  /** Feed an authoritative metrics object from a tick snapshot. */
  update(metrics, tick) {
    this.lastMetrics = metrics;
    for (const entry of this.fields.values()) {
      const value = metrics[entry.key];
      if (typeof value === 'number') entry.target = value;
    }
    if (this.fleetSuffix) this.fleetSuffix.textContent = `/${metrics.fleetSize}`;
    if (this.tickValue) this.tickValue.textContent = tick.toLocaleString();

    if (this.computeFill) {
      const pct = Math.min(100, (metrics.tickComputeP95Ms / this.budgetMs) * 100);
      this.computeFill.style.width = `${pct.toFixed(1)}%`;
      this.computeFill.classList.toggle('is-hot', pct > 60);
    }
    if (this.collisionBadge) {
      this.collisionBadge.classList.toggle('is-bad', metrics.collisions > 0);
    }
    this.spark.setData(metrics.throughputHistory || []);
  }

  /** Called every animation frame. */
  tween(dt) {
    const k = 1 - Math.pow(1 - SMOOTHING, dt / 16.67);
    for (const entry of this.fields.values()) {
      const diff = entry.target - entry.current;
      if (Math.abs(diff) < 0.5 * Math.pow(10, -entry.decimals)) {
        if (entry.current !== entry.target) {
          entry.current = entry.target;
          entry.el.textContent = format(entry.current, entry.decimals);
        }
        continue;
      }
      entry.current += diff * k;
      entry.el.textContent = format(entry.current, entry.decimals);
    }
    this.spark.draw();
  }
}

function decimalsFor(key) {
  if (key === 'tickComputeMs' || key === 'tickComputeP95Ms') return 2;
  if (key === 'avgTaskSeconds') return 1;
  return 0;
}

function format(value, decimals) {
  if (decimals === 0) return Math.round(value).toLocaleString();
  return value.toFixed(decimals);
}

/** Minimal throughput sparkline; area + line, no axes, no chart library. */
class Sparkline {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas?.getContext('2d') ?? null;
    this.data = [];
    this.dirty = true;
    if (canvas) {
      new ResizeObserver(() => { this.dirty = true; }).observe(canvas);
    }
  }

  setData(data) {
    this.data = data;
    this.dirty = true;
  }

  draw() {
    if (!this.ctx || !this.dirty) return;
    this.dirty = false;
    const canvas = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight || 34;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const data = this.data;
    if (data.length < 2) return;

    const max = Math.max(...data, 1) * 1.15;
    const step = w / (data.length - 1);
    const yFor = (v) => h - 2 - (v / max) * (h - 6);

    ctx.beginPath();
    ctx.moveTo(0, yFor(data[0]));
    for (let i = 1; i < data.length; i++) ctx.lineTo(i * step, yFor(data[i]));

    const line = new Path2D();
    line.moveTo(0, yFor(data[0]));
    for (let i = 1; i < data.length; i++) line.lineTo(i * step, yFor(data[i]));

    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, 'rgba(18, 133, 122, 0.28)');
    grad.addColorStop(1, 'rgba(18, 133, 122, 0)');
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.strokeStyle = '#12857a';
    ctx.lineWidth = 1.6;
    ctx.lineJoin = 'round';
    ctx.stroke(line);

    const lastX = (data.length - 1) * step;
    const lastY = yFor(data[data.length - 1]);
    ctx.fillStyle = '#12857a';
    ctx.beginPath();
    ctx.arc(lastX - 1, lastY, 2.4, 0, Math.PI * 2);
    ctx.fill();
  }
}
