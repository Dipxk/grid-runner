/** Black Friday scoreboard overlay. */

export class ScenarioHud {
  constructor(root = document) {
    this.el = root.querySelector('#scenario-hud');
    this.title = root.querySelector('#scenario-title');
    this.blurb = root.querySelector('#scenario-blurb');
    this.time = root.querySelector('#scenario-time');
    this.delivered = root.querySelector('#scenario-delivered');
    this.target = root.querySelector('#scenario-target');
    this.score = root.querySelector('#scenario-score');
    this.grade = root.querySelector('#scenario-grade');
  }

  update(sc) {
    if (!this.el) return;
    if (!sc) {
      this.el.hidden = true;
      return;
    }
    this.el.hidden = false;
    this.el.classList.toggle('is-over', !sc.active && !!sc.grade);
    if (this.title) this.title.textContent = sc.title || 'Scenario';
    if (this.blurb) this.blurb.textContent = sc.blurb || '';
    if (this.time) this.time.textContent = formatRemaining(sc.remaining);
    if (this.delivered) this.delivered.textContent = String(sc.delivered ?? 0);
    if (this.target) this.target.textContent = String(sc.target ?? 0);
    if (this.score) this.score.textContent = String(sc.score ?? 0);
    if (this.grade) {
      this.grade.hidden = !(sc.grade && !sc.active);
      this.grade.textContent = sc.grade ? `Grade ${sc.grade}` : '';
    }
  }
}

function formatRemaining(ticks) {
  const n = Math.max(0, Number(ticks) || 0);
  const m = Math.floor(n / 60);
  const s = n % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}
