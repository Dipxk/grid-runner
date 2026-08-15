/**
 * Control dock: play/pause, speed, fleet size, task burst, jam mode, reset.
 * Every action fires immediately, flashes its own button and raises a toast,
 * so the UI never feels like it swallowed a click.
 */

export class Controls {
  /**
   * @param {object} deps
   * @param {(payload:object)=>void} deps.send
   * @param {import('./toasts.js').Toasts} deps.toasts
   * @param {(on:boolean)=>void} deps.onJamMode
   */
  constructor({ send, toasts, onJamMode }, root = document) {
    this.send = send;
    this.toasts = toasts;
    this.onJamMode = onJamMode;
    this.jamMode = false;
    this.running = true;

    this.playBtn = root.querySelector('#btn-play');
    this.playLabel = root.querySelector('#play-label');
    this.jamBtn = root.querySelector('#btn-jam');
    this.burstBtn = root.querySelector('#btn-burst');
    this.resetBtn = root.querySelector('#btn-reset');
    this.speedGroup = root.querySelector('#speeds');
    this.fleet = root.querySelector('#fleet');
    this.fleetValue = root.querySelector('#fleet-value');
    this.jamHint = root.querySelector('#jam-hint');
    this.app = root.querySelector('#app');

    this.#wire();
  }

  #wire() {
    this.playBtn?.addEventListener('click', () => this.togglePlay());

    this.speedGroup?.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-speed]');
      if (!btn) return;
      for (const chip of this.speedGroup.querySelectorAll('.chip')) chip.classList.remove('is-active');
      btn.classList.add('is-active');
      this.send({ action: 'speed', value: Number(btn.dataset.speed) });
      this.toasts.show(`Speed ${btn.textContent.trim()}`);
    });

    this.burstBtn?.addEventListener('click', () => {
      this.send({ action: 'burst', count: 10 });
      flash(this.burstBtn);
      this.toasts.show('+10 tasks queued', 'good');
    });

    this.jamBtn?.addEventListener('click', () => this.toggleJamMode());

    this.resetBtn?.addEventListener('click', () => {
      this.send({ action: 'reset' });
      flash(this.resetBtn);
      this.toasts.show('Simulation reset');
    });

    let fleetTimer = null;
    this.fleet?.addEventListener('input', () => {
      this.fleetValue.textContent = this.fleet.value;
      clearTimeout(fleetTimer);
      fleetTimer = setTimeout(() => {
        this.send({ action: 'fleet', value: Number(this.fleet.value) });
        this.toasts.show(`Fleet size ${this.fleet.value}`);
      }, 130);
    });

    window.addEventListener('keydown', (event) => {
      if (event.target instanceof HTMLInputElement) return;
      if (event.code === 'Space') {
        event.preventDefault();
        this.togglePlay();
      } else if (event.key === 'j' || event.key === 'J') {
        this.toggleJamMode();
      } else if (event.key === 'b' || event.key === 'B') {
        this.burstBtn?.click();
      }
    });
  }

  togglePlay() {
    this.running = !this.running;
    this.send({ action: this.running ? 'resume' : 'pause' });
    this.setRunning(this.running);
    this.toasts.show(this.running ? 'Running' : 'Paused');
  }

  setRunning(running) {
    this.running = running;
    this.app?.classList.toggle('is-paused', !running);
    if (this.playLabel) this.playLabel.textContent = running ? 'Pause' : 'Play';
  }

  toggleJamMode(force) {
    this.jamMode = force ?? !this.jamMode;
    this.jamBtn?.classList.toggle('is-active', this.jamMode);
    if (this.jamHint) this.jamHint.hidden = !this.jamMode;
    this.onJamMode?.(this.jamMode);
  }

  syncFleet(size) {
    if (!this.fleet || document.activeElement === this.fleet) return;
    // Clamp to the slider's own range: assigning an out-of-range value silently
    // pins the thumb while the readout claims otherwise, and the two then
    // disagree for the rest of the session.
    const min = Number(this.fleet.min) || 0;
    const max = Number(this.fleet.max) || size;
    const clamped = Math.max(min, Math.min(max, size));
    if (Number(this.fleet.value) !== clamped) this.fleet.value = String(clamped);
    if (this.fleetValue.textContent !== String(size)) this.fleetValue.textContent = String(size);
  }
}

function flash(el) {
  el.classList.remove('is-flash');
  void el.offsetWidth; // restart the animation
  el.classList.add('is-flash');
}
