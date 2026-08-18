/**
 * Robot detail panel. Opens on selection, updates every tick while open, and
 * animates out via a CSS transform transition (see .inspector.is-open).
 */

import { STATUS_LABELS } from '../theme.js';

const FAULT_LABELS = {
  robot_offline: 'offline',
  slow_robot: 'slow',
  planner_failure: 'planner failure',
  communication_delay: 'comm delay',
};

const STATE_LABELS = {
  normal: 'normal',
  fault_detected: 'fault detected',
  safe_hold: 'safe hold',
  recovery: 'recovery',
  replanning: 'replanning',
};

export class Inspector {
  constructor(root = document, { onClose, onFault } = {}) {
    this.el = root.querySelector('#inspector');
    this.onFault = onFault;
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
      health: root.querySelector('#insp-health'),
      fault: root.querySelector('#insp-fault'),
      recovery: root.querySelector('#insp-recovery'),
      faultCount: root.querySelector('#insp-fault-count'),
      recoveryCount: root.querySelector('#insp-recovery-count'),
    };
    this.faultSection = root.querySelector('.inspector__faults');
    root.querySelector('#inspector-close')?.addEventListener('click', () => onClose?.());
    this.faultSection?.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-fault]');
      if (!btn) return;
      const kind = btn.dataset.fault;
      if (kind === 'clear') this.onFault?.('clear');
      else this.onFault?.('inject', kind);
    });
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
      const rush = robot.task.rush ? ' · RUSH' : '';
      f.task.textContent = `#${robot.task.id} · ${verb}${rush}`;
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

    const fault = robot.fault || {};
    const health = fault.health || (robot.operational === false ? 'offline' : 'healthy');
    if (f.health) {
      f.health.textContent = health;
      f.health.dataset.health = health;
    }
    if (f.fault) {
      f.fault.textContent = fault.fault ? (FAULT_LABELS[fault.fault] || fault.fault) : '—';
    }
    if (f.recovery) {
      const state = fault.faultState ? (STATE_LABELS[fault.faultState] || fault.faultState) : '—';
      const last = fault.lastRecoverySeconds != null ? ` · last ${fault.lastRecoverySeconds}s` : '';
      f.recovery.textContent = `${state}${last}`;
    }
    if (f.faultCount) f.faultCount.textContent = String(fault.faultCount ?? 0);
    if (f.recoveryCount) f.recoveryCount.textContent = String(fault.recoveryCount ?? 0);

    if (this.faultSection) {
      this.faultSection.dataset.robot = String(robot.id);
    }
  }
}
