/**
 * RoboFleet client entry point.
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
import { ScenarioHud } from './ui/scenario.js';
import { SoundBed } from './audio/sound.js';
import { OpsTicker } from './ui/ticker.js';
import { CELL_TYPE } from './theme.js';

const canvas = document.getElementById('scene');
const ctx = canvas.getContext('2d');
const connectionEl = document.getElementById('connection');

const camera = new Camera();
const floor = new FloorRenderer();
const scene = new SceneRenderer();
const buffer = new TickBuffer();
const metrics = new MetricsPanel();
const toasts = new Toasts(document.getElementById('toasts'));
const inspector = new Inspector(document, {
  onClose: () => selectRobot(null),
  onFault: (action, type) => {
    if (state.selectedId === null) return;
    if (action === 'clear') {
      socket.send({ action: 'clear_fault', robot: state.selectedId });
      toasts.show(`R${state.selectedId} fault cleared`, 'good');
      return;
    }
    socket.send({ action: 'fault', robot: state.selectedId, type });
    toasts.show(`R${state.selectedId} · ${type.replace(/_/g, ' ')}`, 'warn');
  },
});
const scenarioHud = new ScenarioHud(document);
const sound = new SoundBed();
const ticker = new OpsTicker(document);
const followChip = document.getElementById('follow-chip');
const povHint = document.getElementById('pov-hint');
const povHintDismiss = document.getElementById('pov-hint-dismiss');

const state = {
  world: null,
  selectedId: null,
  hoverCell: null,
  hoverRobotId: null,
  tool: 'none',
  orderPickup: null,
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
    controls.syncDemand(msg.manualDemand);
    resize();
    if (msg.snapshot) ingest(msg.snapshot);
  },
  onTick: (msg) => {
    buffer.setInterval(msg.tickIntervalMs);
    metrics.setBudget(msg.tickIntervalMs);
    controls.syncFleet(msg.fleetSize);
    controls.setRunning(msg.running);
    if (typeof msg.manualDemand === 'boolean') controls.syncDemand(msg.manualDemand);
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
    if (msg.rush) {
      if (!msg.rush.ok) toasts.show(msg.rush.reason === 'click a pick face' ? 'Rush orders go on a pick face' : 'Could not place rush order', 'bad');
      else {
        toasts.show(`Rush order #${msg.rush.task} at ${msg.rush.cell[0]}, ${msg.rush.cell[1]}`, 'good');
        sound.rush();
      }
    }
    if (msg.order) {
      if (!msg.order.ok) {
        toasts.show(msg.order.reason === 'click a dock door' ? 'Finish on a dock door' : 'Start on a pick slot', 'bad');
      } else {
        toasts.show(`Order #${msg.order.task} · ${doorLabel(msg.order.dropoff)}`, 'good');
        sound.rush();
        state.orderPickup = null;
        controls.setOrderHint('pick');
      }
    }
    if (typeof msg.manualDemand === 'boolean') controls.syncDemand(msg.manualDemand);
    if (msg.scenario && msg.world) {
      state.world = msg.world;
      if (msg.snapshot) ingest(msg.snapshot);
      scenarioHud.update(msg.scenario);
      sound.scenarioStart();
      controls.syncDemand(false);
      resize();
    }
    if (msg.action === 'reset') {
      scenarioHud.update(null);
      controls.syncDemand(false);
      state.orderPickup = null;
    }
  },
});

function ingest(snapshot) {
  buffer.push(snapshot);
  metrics.update(snapshot.metrics, snapshot.tick);

  if (snapshot.tick < state.seenEventTick) state.seenEventTick = -1;
  if (snapshot.tick > state.seenEventTick) {
    const now = performance.now();
    for (const event of snapshot.events || []) {
      if (event.type === 'delivered') {
        if (event.cell) scene.addPulse(event.cell[0], event.cell[1], 'delivered', now + 340);
        sound.delivered();
        ticker.push(`Order #${orderId(event, snapshot)} out · ${doorLabel(event.cell)}`, 'good');
      } else if (event.type === 'picked') {
        if (event.cell) scene.addPulse(event.cell[0], event.cell[1], 'picked', now + 340);
        sound.picked();
        ticker.push(`Order #${orderId(event, snapshot)} picked`, 'good');
      } else if (event.type === 'jam_added') {
        sound.jam();
        ticker.push(`Aisle blocked ${cellLabel(event.cell)}`.trim(), 'warn');
      } else if (event.type === 'jam_cleared') {
        ticker.push(`Aisle clear ${cellLabel(event.cell)}`.trim(), 'good');
      } else if (event.type === 'rush') {
        ticker.push(`Rush order #${event.task} · pick ${cellLabel(event.cell)}`.trim(), 'warn');
      } else if (event.type === 'order') {
        ticker.push(`Order #${event.task} placed · ${doorLabel(event.dropoff)}`, 'good');
      } else if (event.type === 'demand') {
        ticker.push(event.manual ? 'You dispatch — random orders paused' : 'Live demand resumed', event.manual ? 'warn' : 'good');
      } else if (event.type === 'scenario_start') {
        const label = event.id === 'resilience_test' ? 'Resilience Test' : 'Black Friday — peak hour';
        ticker.push(label, 'warn');
      } else if (event.type === 'scenario_over') {
        sound.scenarioOver(event.grade);
        const name = event.id === 'resilience_test' ? 'Resilience Test' : 'Black Friday';
        toasts.show(`${name} over — grade ${event.grade}, score ${event.score}`, event.grade === 'F' ? 'bad' : 'good');
        ticker.push(`${name} over · grade ${event.grade}`, event.grade === 'F' ? 'warn' : 'good');
      } else if (event.type === 'fault_detected') {
        ticker.push(`R${event.robot} fault · ${faultLabel(event.fault)}`, 'warn');
      } else if (event.type === 'robot_offline') {
        ticker.push(`R${event.robot} OFFLINE`, 'warn');
      } else if (event.type === 'robot_recovered') {
        ticker.push(`R${event.robot} RECOVERED — navigation resumed`, 'good');
      } else if (event.type === 'task_reassigned') {
        ticker.push(`R${event.fromRobot} OFFLINE — task #${event.task} returned to queue`, 'warn');
      } else if (event.type === 'planner_failure') {
        ticker.push(`R${event.robot} PLANNER FAILURE — safe hold`, 'warn');
      } else if (event.type === 'recovery_started') {
        ticker.push(`R${event.robot} recovery started`, 'warn');
      } else if (event.type === 'recovery_completed') {
        const sec = event.latencyTicks != null ? Number(event.latencyTicks).toFixed(1) : null;
        ticker.push(
          sec ? `R${event.robot} RECOVERED — navigation resumed in ${sec}s` : `R${event.robot} RECOVERED`,
          'good',
        );
      } else if (event.type === 'recovery_required') {
        ticker.push(`R${event.robot} carrying task #${event.task} — manual recovery required`, 'warn');
      }
    }
    state.seenEventTick = snapshot.tick;
  }
  scenarioHud.update(snapshot.scenario);

  if (state.selectedId !== null) {
    const robot = snapshot.robots.find((r) => r.id === state.selectedId);
    inspector.update(robot ?? null);
    if (!robot) {
      state.selectedId = null;
      if (followChip) followChip.hidden = true;
    }
  }
}

// ── controls ───────────────────────────────────────────────────────────────
const controls = new Controls(
  {
    send: (payload) => socket.send(payload),
    toasts,
    onTool: (tool) => {
      state.tool = tool;
      state.orderPickup = null;
      canvas.classList.toggle('is-jam-mode', tool === 'jam');
      canvas.classList.toggle('is-rush-mode', tool === 'rush');
      canvas.classList.toggle('is-order-mode', tool === 'order');
    },
    onSound: () => sound.toggle(),
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

function hidePovHint() {
  if (povHint) povHint.hidden = true;
  state.povHintDismissed = true;
}

if (povHintDismiss) {
  povHintDismiss.addEventListener('click', (event) => {
    event.stopPropagation();
    hidePovHint();
  });
}

function selectRobot(id) {
  state.selectedId = id;
  if (followChip) followChip.hidden = id === null;
  if (id !== null) hidePovHint();
  if (id === null) {
    inspector.update(null);
    if (povHint && !state.povHintDismissed) povHint.hidden = false;
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
  const hovered = inside && state.tool === 'none' ? robotAt(cell, pointerPrecise(event)) : null;
  state.hoverRobotId = hovered ? hovered.id : null;
  canvas.classList.toggle('is-hover-robot', !!hovered);
});

canvas.addEventListener('mouseleave', () => { state.hoverCell = null; });

canvas.addEventListener('click', (event) => {
  const cell = pointerCell(event);
  if (!state.world) return;
  if (cell[0] < 0 || cell[1] < 0 || cell[0] >= state.world.width || cell[1] >= state.world.height) return;

  if (state.tool === 'jam') {
    socket.send({ action: 'jam', x: cell[0], y: cell[1] });
    return;
  }
  if (state.tool === 'rush') {
    socket.send({ action: 'rush', x: cell[0], y: cell[1] });
    return;
  }
  if (state.tool === 'order') {
    if (!state.orderPickup) {
      const pickup = resolveStation(cell, CELL_TYPE.PICKUP);
      if (!pickup) {
        toasts.show('Click a pick slot first', 'bad');
        return;
      }
      state.orderPickup = pickup;
      controls.setOrderHint('dock');
      toasts.show('Now click the dock it should leave from', 'good');
      return;
    }
    socket.send({
      action: 'order',
      x: state.orderPickup[0],
      y: state.orderPickup[1],
      dropX: cell[0],
      dropY: cell[1],
    });
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
      console.error('[robofleet] frame error', error);
    }
  }
  requestAnimationFrame(frame);
}

function renderFrame(now) {
  const dt = Math.min(64, now - state.lastFrame);
  state.lastFrame = now;

  metrics.tween(dt);

  const sample = buffer.sample(now);
  const snapshot = buffer.latest();
  const follow = sample?.robots.find((r) => r.id === state.selectedId);
  camera.advance(dt, follow ? [follow.px, follow.py] : null);

  if (state.world) {
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    ctx.clearRect(0, 0, camera.viewW, camera.viewH);

    const floorCanvas = floor.render(state.world, camera, state.dpr);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(floorCanvas, 0, 0);
    ctx.restore();

    if (sample && snapshot) {
      scene.draw(ctx, {
        camera,
        robots: sample.robots,
        jams: snapshot.jams || [],
        selectedId: state.selectedId,
        hoverRobotId: state.hoverRobotId,
        hoverCell: state.hoverCell,
        jamMode: state.tool === 'jam',
        rushMode: state.tool === 'rush',
        orderMode: state.tool === 'order',
        orderPickup: state.orderPickup,
        dispatch: snapshot.dispatch || [],
        world: state.world,
        now,
        dt,
        tick: sample.tick,
      });
    }
  }
}

function cellTypeAt(cell) {
  const row = state.world?.cells?.[cell[1]];
  if (row == null || cell[0] < 0 || cell[0] >= row.length) return -1;
  return Number(row[cell[0]]);
}

function resolveStation(cell, kind) {
  if (cellTypeAt(cell) === kind) return cell;
  const [x, y] = cell;
  for (const next of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) {
    if (cellTypeAt(next) === kind) return next;
  }
  return null;
}

function cellLabel(cell) {
  return cell ? `${cell[0]}, ${cell[1]}` : '';
}

function orderId(event, snapshot) {
  if (event.task != null) return event.task;
  const robot = snapshot.robots?.find((r) => r.id === event.robot);
  return robot?.task?.id ?? robot?.taskId ?? '—';
}

function doorLabel(cell) {
  const docks = state.world?.dropoffs;
  if (cell && docks?.length) {
    const i = docks.findIndex((d) => d[0] === cell[0] && d[1] === cell[1]);
    if (i >= 0) return `DOOR ${String(i + 1).padStart(2, '0')}`;
  }
  return cell ? `door ${cell[0]},${cell[1]}` : 'door';
}

function faultLabel(type) {
  return String(type || '').replace(/_/g, ' ');
}

socket.connect();
requestAnimationFrame(frame);

// Debug handle: `__roboFleet.buffer.sample(performance.now())` shows exactly
// what the renderer sees on the current frame, and `renderOnce()` forces a
// synchronous repaint (useful for screenshots and headless capture, where
// requestAnimationFrame may be throttled).
window.__roboFleet = { buffer, camera, scene, state, socket, renderOnce: () => renderFrame(performance.now()) };
