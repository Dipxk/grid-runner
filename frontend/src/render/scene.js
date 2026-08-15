/**
 * Dynamic layer: jams, planned paths, robots and event pulses.
 * Everything here is driven by the interpolated sample from the tick buffer,
 * so motion is continuous even though the simulation is discrete.
 */

import { JAM, statusColor, statusDark } from '../theme.js';

const FACING_ANGLE = { east: 0, south: Math.PI / 2, west: Math.PI, north: -Math.PI / 2 };

export class SceneRenderer {
  constructor() {
    /** @type {Array<{x:number,y:number,t0:number,kind:string}>} */
    this.pulses = [];
    /** @type {Map<string, number>} jam cell key -> first seen timestamp */
    this.jamSeen = new Map();
    /** @type {Map<number, number>} robot id -> smoothed body angle */
    this.angles = new Map();
  }

  addPulse(x, y, kind, now) {
    this.pulses.push({ x, y, t0: now, kind });
    if (this.pulses.length > 40) this.pulses.shift();
  }

  /**
   * @param {CanvasRenderingContext2D} ctx
   * @param {object} view {camera, robots, jams, selectedId, hoverCell, jamMode, now, dt}
   */
  draw(ctx, view) {
    const { camera, robots, jams, selectedId, hoverRobotId, hoverCell, jamMode, now } = view;

    this.#drawJams(ctx, camera, jams, now);
    if (hoverCell) this.#drawHover(ctx, camera, hoverCell, jamMode);

    const selected = robots.find((r) => r.id === selectedId);
    if (selected) this.#drawPath(ctx, camera, selected, now);

    this.#drawPulses(ctx, camera, now);

    // Selected robot draws last so it always reads on top of traffic.
    for (const robot of robots) {
      if (robot.id === selectedId) continue;
      this.#drawRobot(ctx, camera, robot, false, now, view.dt, robot.id === hoverRobotId);
    }
    if (selected) this.#drawRobot(ctx, camera, selected, true, now, view.dt, false);
  }

  // ------------------------------------------------------------------
  #drawJams(ctx, camera, jams, now) {
    const cell = camera.cell;
    const live = new Set();

    for (const jam of jams) {
      const key = `${jam.x},${jam.y}`;
      live.add(key);
      if (!this.jamSeen.has(key)) this.jamSeen.set(key, now);

      // Fade in over 320ms, fade out over the last few ticks of its life.
      const age = now - this.jamSeen.get(key);
      const fadeIn = Math.min(1, age / 320);
      const fadeOut = jam.ttl <= 6 ? Math.max(0.25, jam.ttl / 6) : 1;
      const alpha = fadeIn * fadeOut;
      const pulse = 0.5 + 0.5 * Math.sin(now / 420 + (jam.x + jam.y));

      const [px, py] = camera.cellToPx(jam.x, jam.y);
      const inset = cell * 0.04;

      ctx.save();
      ctx.globalAlpha = alpha;

      // Wash the cell first so the hazard reads even over dark shelving.
      ctx.fillStyle = 'rgba(255, 241, 237, 0.55)';
      ctx.beginPath();
      roundRect(ctx, px + inset, py + inset, cell - inset * 2, cell - inset * 2, cell * 0.18);
      ctx.fill();
      ctx.beginPath();
      roundRect(ctx, px + inset, py + inset, cell - inset * 2, cell - inset * 2, cell * 0.18);
      ctx.fillStyle = JAM.fill;
      ctx.fill();

      // Hazard stripes, clipped to the cell.
      ctx.save();
      ctx.clip();
      ctx.strokeStyle = JAM.stripe;
      ctx.lineWidth = Math.max(1.8, cell * 0.14);
      ctx.beginPath();
      for (let o = -cell; o < cell * 2; o += cell * 0.38) {
        ctx.moveTo(px + o, py);
        ctx.lineTo(px + o + cell, py + cell);
      }
      ctx.stroke();
      ctx.restore();

      ctx.strokeStyle = JAM.edge;
      ctx.globalAlpha = alpha * (0.7 + 0.3 * pulse);
      ctx.lineWidth = Math.max(1.6, cell * 0.1);
      ctx.beginPath();
      roundRect(ctx, px + inset, py + inset, cell - inset * 2, cell - inset * 2, cell * 0.18);
      ctx.stroke();
      ctx.restore();
    }

    for (const key of [...this.jamSeen.keys()]) {
      if (!live.has(key)) this.jamSeen.delete(key);
    }
  }

  #drawHover(ctx, camera, hoverCell, jamMode) {
    const [px, py] = camera.cellToPx(hoverCell[0], hoverCell[1]);
    const cell = camera.cell;
    ctx.save();
    ctx.strokeStyle = jamMode ? 'rgba(207, 81, 55, 0.85)' : 'rgba(37, 56, 65, 0.35)';
    ctx.lineWidth = 1.6;
    ctx.setLineDash(jamMode ? [cell * 0.22, cell * 0.16] : []);
    roundRectPath(ctx, px + 1, py + 1, cell - 2, cell - 2, cell * 0.16);
    ctx.stroke();
    ctx.restore();
  }

  // ------------------------------------------------------------------
  #drawPath(ctx, camera, robot, now) {
    const path = robot.path || [];
    if (path.length === 0) return;
    const cell = camera.cell;
    const color = statusColor(robot.status);

    const pts = [[robot.px, robot.py], ...path.map(([x, y]) => [x, y])];

    ctx.save();
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    // Soft underlay so the route stays legible over shelving.
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.65)';
    ctx.lineWidth = cell * 0.3;
    strokePolyline(ctx, camera, pts);

    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.85;
    ctx.lineWidth = cell * 0.15;
    ctx.setLineDash([cell * 0.42, cell * 0.3]);
    ctx.lineDashOffset = -((now / 42) % (cell * 0.72));
    strokePolyline(ctx, camera, pts);
    ctx.setLineDash([]);

    // Waypoints.
    ctx.globalAlpha = 0.5;
    ctx.fillStyle = color;
    for (let i = 0; i < path.length - 1; i++) {
      const [cx, cy] = camera.centerToPx(path[i][0], path[i][1]);
      ctx.beginPath();
      ctx.arc(cx, cy, cell * 0.06, 0, Math.PI * 2);
      ctx.fill();
    }

    // Destination marker.
    const goal = robot.goal || path[path.length - 1];
    if (goal) {
      const [gx, gy] = camera.centerToPx(goal[0], goal[1]);
      const r = cell * 0.34 + Math.sin(now / 320) * cell * 0.03;
      ctx.globalAlpha = 0.95;
      ctx.strokeStyle = color;
      ctx.lineWidth = cell * 0.09;
      ctx.beginPath();
      ctx.arc(gx, gy, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(gx, gy, cell * 0.1, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }
    ctx.restore();
  }

  // ------------------------------------------------------------------
  #drawPulses(ctx, camera, now) {
    const cell = camera.cell;
    this.pulses = this.pulses.filter((p) => now - p.t0 < 900);
    for (const pulse of this.pulses) {
      // Pulses are scheduled slightly in the future so they fire when the
      // interpolated view actually reaches the tick that produced them.
      if (now < pulse.t0) continue;
      const t = (now - pulse.t0) / 900;
      const [cx, cy] = camera.centerToPx(pulse.x, pulse.y);
      const ease = 1 - Math.pow(1 - t, 3);
      ctx.save();
      ctx.globalAlpha = (1 - t) * 0.7;
      ctx.strokeStyle = pulse.kind === 'delivered' ? '#12857a' : '#d5872a';
      ctx.lineWidth = Math.max(0.5, cell * 0.1 * (1 - t * 0.6));
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(0.5, cell * (0.3 + ease * 0.9)), 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  // ------------------------------------------------------------------
  #drawRobot(ctx, camera, robot, isSelected, now, dt, isHovered = false) {
    const cell = camera.cell;
    const [cx, cy] = camera.centerToPx(robot.px, robot.py);
    const color = statusColor(robot.status);
    const edge = statusDark(robot.status);
    const idle = robot.status === 'idle';
    const size = cell * (idle ? 0.6 : 0.68);

    // Smoothly rotate the chassis toward the direction of travel.
    const targetAngle = FACING_ANGLE[robot.facing] ?? 0;
    const prev = this.angles.get(robot.id);
    let angle = targetAngle;
    if (prev !== undefined) {
      let delta = targetAngle - prev;
      while (delta > Math.PI) delta -= Math.PI * 2;
      while (delta < -Math.PI) delta += Math.PI * 2;
      angle = prev + delta * Math.min(1, dt / 90);
    }
    this.angles.set(robot.id, angle);

    ctx.save();

    // Contact shadow — one soft shadow only, no stacked glows.
    ctx.globalAlpha = idle ? 0.1 : 0.16;
    ctx.fillStyle = '#0e1a1f';
    ctx.beginPath();
    ctx.ellipse(cx, cy + size * 0.42, size * 0.46, size * 0.2, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;

    if (isSelected) {
      const r = size * 0.85 + Math.sin(now / 260) * cell * 0.04;
      ctx.strokeStyle = 'rgba(14, 26, 31, 0.28)';
      ctx.lineWidth = Math.max(1.4, cell * 0.055);
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(0.5, r), 0, Math.PI * 2);
      ctx.stroke();
    } else if (isHovered) {
      // Affordance: show the click target before the user commits to it.
      ctx.strokeStyle = 'rgba(14, 26, 31, 0.18)';
      ctx.lineWidth = Math.max(1.2, cell * 0.045);
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(0.5, size * 0.8), 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.translate(cx, cy);
    ctx.rotate(angle);

    // Chassis.
    ctx.fillStyle = color;
    ctx.strokeStyle = edge;
    ctx.lineWidth = Math.max(1, cell * 0.05);
    roundRectPath(ctx, -size / 2, -size / 2, size, size, size * 0.26);
    ctx.fill();
    ctx.stroke();

    // Leading-edge marker so heading is readable at a glance.
    ctx.fillStyle = 'rgba(255, 255, 255, 0.78)';
    ctx.beginPath();
    ctx.moveTo(size * 0.16, -size * 0.2);
    ctx.lineTo(size * 0.36, 0);
    ctx.lineTo(size * 0.16, size * 0.2);
    ctx.closePath();
    ctx.fill();

    // Payload block when carrying.
    if (robot.status === 'carrying') {
      const p = size * 0.34;
      ctx.fillStyle = '#fbf3e6';
      ctx.strokeStyle = 'rgba(87, 55, 12, 0.5)';
      ctx.lineWidth = Math.max(1, cell * 0.035);
      roundRectPath(ctx, -p / 2 - size * 0.06, -p / 2, p, p, p * 0.2);
      ctx.fill();
      ctx.stroke();
    }

    ctx.restore();

    // Id badge for the selected robot only — keeps the floor uncluttered.
    if (isSelected && cell >= 12) {
      ctx.save();
      ctx.fillStyle = '#0e1a1f';
      ctx.font = `600 ${Math.max(9, Math.round(cell * 0.42))}px "IBM Plex Mono", monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(`R${robot.id}`, cx, cy - size * 0.85);
      ctx.restore();
    }
  }
}

// ---------------------------------------------------------------------------
function strokePolyline(ctx, camera, pts) {
  ctx.beginPath();
  const [sx, sy] = camera.centerToPx(pts[0][0], pts[0][1]);
  ctx.moveTo(sx, sy);
  for (let i = 1; i < pts.length; i++) {
    const [x, y] = camera.centerToPx(pts[i][0], pts[i][1]);
    ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  roundRect(ctx, x, y, w, h, r);
}

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
}
