/**
 * Grid Runner client entry point.
 *
 * Responsibilities are deliberately split:
 *   net/socket.js       transport + reconnect
 *   state/tickBuffer.js authoritative snapshots -> smooth interpolated view
 *   render/*            canvas drawing (static floor cached, dynamic layer per frame)
 *   ui/*                DOM chrome (metrics, inspector, controls, toasts)
 *
 * This file owns only the render loop and the wiring between those pieces.
 */

import { SimSocket } from './net/socket.js';
import { TickBuffer } from './state/tickBuffer.js';
import { Camera } from './render/camera.js';
import { FloorRenderer } from './render/floor.js';
import { SceneRenderer } from './render/scene.js';
import { MetricsPanel } from './ui/metrics.js';
import { Inspector } from './ui/inspector.js';
import { Controls } from './ui/controls.js';
import { Toasts } from './ui/toasts.js';

const canvas = document.getElementById('scene');
const ctx = canvas.getContext('2d');
const connectionEl = document.getElementById('connection');

const camera = new Camera();
const floor = new FloorRenderer();
const scene = new SceneRenderer();
const buffer = new TickBuffer();
const metrics = new MetricsPanel();
const toasts = new Toasts(document.getElementById('toasts'));
const inspector = new Inspector(document, { onClose: () => selectRobot(null) });

const state = {
  world: null,
  selectedId: null,
  hoverCell: null,
  hoverRobotId: null,
  jamMode: false,
  dpr: window.devicePixelRatio || 1,
  lastFrame: performance.now(),
  seenEventTick: -1,
};

// ── networking ─────────────────────────────────────────────────────────────
const socket = new SimSocket({
  onStatus: (status) => {
    connectionEl.dataset.state = status === 'live' ? 'live' : status;
    connectionEl.querySelector('.label').textContent = status === 'live' ? 'live' : status;
  },
  onInit: (msg) => {
    state.world = msg.world;
    buffer.setInterval(msg.tickIntervalMs);
    metrics.setBudget(msg.tickIntervalMs);
    controls.setRunning(msg.running);
    controls.syncFleet(msg.fleetSize);
    resize();
    if (msg.snapshot) ingest(msg.snapshot);
  },
  onTick: (msg) => {
    buffer.setInterval(msg.tickIntervalMs);
    metrics.setBudget(msg.tickIntervalMs);
    controls.syncFleet(msg.fleetSize);
    controls.setRunning(msg.running);
    ingest(msg);
  },
  onAck: (msg) => {
    if (typeof msg.running === 'boolean') controls.setRunning(msg.running);
    if (msg.tickIntervalMs) {
      buffer.setInterval(msg.tickIntervalMs);
      metrics.setBudget(msg.tickIntervalMs);
    }
    if (msg.jam) {
      const [x, y] = msg.jam.cell;
      if (!msg.jam.ok) toasts.show(`No jam here — ${x}, ${y} is a station`, 'bad');
      else if (msg.jam.action === 'cleared') toasts.show(`Jam cleared at ${x}, ${y}`, 'good');
      else toasts.show(`Jam dropped at ${x}, ${y}`, 'warn');
    }
  },
});

function ingest(snapshot) {
  buffer.push(snapshot);
  metrics.update(snapshot.metrics, snapshot.tick);

  const now = performance.now();
  for (const event of snapshot.events || []) {
    if (event.type === 'delivered' && event.cell) scene.addPulse(event.cell[0], event.cell[1], 'delivered', now + 340);
    else if (event.type === 'picked' && event.cell) scene.addPulse(event.cell[0], event.cell[1], 'picked', now + 340);
  }

  if (state.selectedId !== null) {
    const robot = snapshot.robots.find((r) => r.id === state.selectedId);
    inspector.update(robot ?? null);
    if (!robot) state.selectedId = null;
  }
}

// ── controls ───────────────────────────────────────────────────────────────
const controls = new Controls(
  {
    send: (payload) => socket.send(payload),
    toasts,
    onJamMode: (on) => {
      state.jamMode = on;
      canvas.classList.toggle('is-jam-mode', on);
      if (on) toasts.show('Jam mode on — click a cell', 'warn');
    },
  },
  document,
);

// ── canvas interaction ─────────────────────────────────────────────────────
function pointerCell(event) {
  const rect = canvas.getBoundingClientRect();
  return camera.pxToCell(event.clientX - rect.left, event.clientY - rect.top);
}

/**
 * Hit-test against the *interpolated* positions, not the authoritative grid
 * cells: the robot the user sees is up to a cell away from where the server
 * says it is, so exact cell matching makes moving robots feel unclickable.
 * A radius slightly under one cell keeps neighbouring robots unambiguous.
 */
function robotAt(cell, precise) {
  const sample = buffer.sample(performance.now());
  if (!sample) return null;
  const [tx, ty] = precise ?? [cell[0] + 0.5, cell[1] + 0.5];
  let best = null;
  let bestDist = 0.85;
  for (const robot of sample.robots) {
    const dist = Math.hypot(robot.px + 0.5 - tx, robot.py + 0.5 - ty);
    if (dist < bestDist) {
      bestDist = dist;
      best = robot;
    }
  }
  if (best) return best;
  const snapshot = buffer.latest();
  return snapshot?.robots.find((r) => r.x === cell[0] && r.y === cell[1]) ?? null;
}

/** Pointer position in fractional grid units, for precise hit-testing. */
function pointerPrecise(event) {
  const rect = canvas.getBoundingClientRect();
  return [
    (event.clientX - rect.left - camera.originX) / camera.cell,
    (event.clientY - rect.top - camera.originY) / camera.cell,
  ];
}

function selectRobot(id) {
  state.selectedId = id;
  if (id === null) {
    inspector.update(null);
    return;
  }
  const snapshot = buffer.latest();
  inspector.update(snapshot?.robots.find((r) => r.id === id) ?? null);
}

canvas.addEventListener('mousemove', (event) => {
  const cell = pointerCell(event);
  const inside =
    state.world &&
    cell[0] >= 0 && cell[1] >= 0 &&
    cell[0] < state.world.width && cell[1] < state.world.height;
  state.hoverCell = inside ? cell : null;
  const hovered = inside && !state.jamMode ? robotAt(cell, pointerPrecise(event)) : null;
  state.hoverRobotId = hovered ? hovered.id : null;
  canvas.classList.toggle('is-hover-robot', !!hovered);
});

canvas.addEventListener('mouseleave', () => { state.hoverCell = null; });

canvas.addEventListener('click', (event) => {
  const cell = pointerCell(event);
  if (!state.world) return;
  if (cell[0] < 0 || cell[1] < 0 || cell[0] >= state.world.width || cell[1] >= state.world.height) return;

  if (state.jamMode) {
    // Feedback is driven by the server ack so a refused cell reads honestly.
    socket.send({ action: 'jam', x: cell[0], y: cell[1] });
    return;
  }
  const robot = robotAt(cell, pointerPrecise(event));
  selectRobot(robot ? robot.id : null);
});

// ── resize ─────────────────────────────────────────────────────────────────
function resize() {
  const rect = canvas.getBoundingClientRect();
  state.dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * state.dpr));
  canvas.height = Math.max(1, Math.round(rect.height * state.dpr));
  if (state.world) camera.fit(rect.width, rect.height, state.world.width, state.world.height);
}

new ResizeObserver(resize).observe(canvas);
window.addEventListener('resize', resize);

// ── render loop ────────────────────────────────────────────────────────────
function frame(now) {
  try {
    renderFrame(now);
  } catch (error) {
    // A render bug must never kill the animation loop: log once per message
    // and keep going so the rest of the UI stays interactive.
    if (state.lastError !== String(error)) {
      state.lastError = String(error);
      console.error('[grid-runner] frame error', error);
    }
  }
  requestAnimationFrame(frame);
}

function renderFrame(now) {
  const dt = Math.min(64, now - state.lastFrame);
  state.lastFrame = now;

  metrics.tween(dt);

  if (state.world) {
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    ctx.clearRect(0, 0, camera.viewW, camera.viewH);

    const floorCanvas = floor.render(state.world, camera, state.dpr);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(floorCanvas, 0, 0);
    ctx.restore();

    const sample = buffer.sample(now);
    const snapshot = buffer.latest();
    if (sample && snapshot) {
      scene.draw(ctx, {
        camera,
        robots: sample.robots,
        jams: snapshot.jams || [],
        selectedId: state.selectedId,
        hoverRobotId: state.hoverRobotId,
        hoverCell: state.hoverCell,
        jamMode: state.jamMode,
        now,
        dt,
        tick: sample.tick,
      });
    }
  }
}

socket.connect();
requestAnimationFrame(frame);

// Debug handle: `__gridRunner.buffer.sample(performance.now())` shows exactly
// what the renderer sees on the current frame, and `renderOnce()` forces a
// synchronous repaint (useful for screenshots and headless capture, where
// requestAnimationFrame may be throttled).
window.__gridRunner = { buffer, camera, scene, state, socket, renderOnce: () => renderFrame(performance.now()) };
