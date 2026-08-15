/**
 * Robot detail panel. Opens on selection, updates every tick while open, and
 * animates out via a CSS transform transition (see .inspector.is-open).
 */

import { STATUS_LABELS } from '../theme.js';

export class Inspector {
  constructor(root = document, { onClose } = {}) {
    this.el = root.querySelector('#inspector');
    this.fields = {
      id: root.querySelector('#insp-id'),
      status: root.querySelector('#insp-status'),
      pos: root.querySelector('#insp-pos'),
      task: root.querySelector('#insp-task'),
      dest: root.querySelector('#insp-dest'),
      eta: root.querySelector('#insp-eta'),
      queue: root.querySelector('#insp-queue'),
      completed: root.querySelector('#insp-completed'),
      replans: root.querySelector('#insp-replans'),
      reroutes: root.querySelector('#insp-reroutes'),
      blocked: root.querySelector('#insp-blocked'),
    };
    root.querySelector('#inspector-close')?.addEventListener('click', () => onClose?.());
  }

  close() {
    this.el?.classList.remove('is-open');
  }

  /** @param {object|null} robot authoritative (non-interpolated) robot payload */
  update(robot) {
    if (!this.el) return;
    if (!robot) {
      this.close();
      return;
    }
    this.el.classList.add('is-open');
    const f = this.fields;
    f.id.textContent = `R${robot.id}`;
    f.status.textContent = STATUS_LABELS[robot.status] || robot.status;
    f.status.dataset.status = robot.status;
    f.pos.textContent = `${robot.x}, ${robot.y}`;

    if (robot.task) {
      const verb = robot.task.state === 'carried' ? 'carrying' : 'fetching';
      f.task.textContent = `#${robot.task.id} · ${verb}`;
      const dest = robot.task.state === 'carried' ? robot.task.dropoff : robot.task.pickup;
      f.dest.textContent = `${dest[0]}, ${dest[1]}`;
    } else {
      f.task.textContent = 'none';
      f.dest.textContent = robot.goal ? `${robot.goal[0]}, ${robot.goal[1]}` : '—';
    }

    const steps = (robot.path || []).length;
    f.eta.textContent = steps ? `${steps}` : '0';
    f.queue.textContent = String(robot.queued ?? 0);
    f.completed.textContent = String(robot.completed ?? 0);
    f.replans.textContent = String(robot.stats?.replans ?? 0);
    f.reroutes.textContent = String(robot.stats?.reroutes ?? 0);
    f.blocked.textContent = String(robot.stats?.blockedTicks ?? 0);
  }
}
