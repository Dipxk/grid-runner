/**
 * Control dock: play/pause, speed, fleet, dispatcher tools, scenario, sound.
 * Every action fires immediately, flashes its own button and raises a toast.
 */

export class Controls {
  /**
   * @param {object} deps
   * @param {(payload:object)=>void} deps.send
   * @param {import('./toasts.js').Toasts} deps.toasts
   * @param {(tool:'none'|'jam'|'rush'|'order')=>void} deps.onTool
   * @param {()=>boolean} [deps.onSound]
   */
  constructor({ send, toasts, onTool, onSound }, root = document) {
    this.send = send;
    this.toasts = toasts;
    this.onTool = onTool;
    this.onSound = onSound;
    this.tool = 'none';
    this.running = true;

    this.playBtn = root.querySelector('#btn-play');
    this.playLabel = root.querySelector('#play-label');
    this.jamBtn = root.querySelector('#btn-jam');
    this.rushBtn = root.querySelector('#btn-rush');
    this.orderBtn = root.querySelector('#btn-order');
    this.demandBtn = root.querySelector('#btn-demand');
    this.demandLabel = root.querySelector('#demand-label');
    this.burstBtn = root.querySelector('#btn-burst');
    this.scenarioBtn = root.querySelector('#btn-scenario');
    this.resilienceBtn = root.querySelector('#btn-resilience');
    this.soundBtn = root.querySelector('#btn-sound');
    this.resetBtn = root.querySelector('#btn-reset');
    this.speedGroup = root.querySelector('#speeds');
    this.fleet = root.querySelector('#fleet');
    this.fleetValue = root.querySelector('#fleet-value');
    this.jamHint = root.querySelector('#jam-hint');
    this.rushHint = root.querySelector('#rush-hint');
    this.orderHint = root.querySelector('#order-hint');
    this.app = root.querySelector('#app');
    this.dock = root.querySelector('#dock');
    this.dockCollapse = root.querySelector('#btn-dock-collapse');
    this.manualDemand = false;

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

    this.jamBtn?.addEventListener('click', () => this.setTool(this.tool === 'jam' ? 'none' : 'jam'));
    this.rushBtn?.addEventListener('click', () => this.setTool(this.tool === 'rush' ? 'none' : 'rush'));
    this.orderBtn?.addEventListener('click', () => this.setTool(this.tool === 'order' ? 'none' : 'order'));
    this.demandBtn?.addEventListener('click', () => this.toggleDemand());

    this.scenarioBtn?.addEventListener('click', () => {
      this.send({ action: 'scenario', name: 'black_friday' });
      flash(this.scenarioBtn);
      this.toasts.show('Black Friday — keep the docks moving', 'warn');
    });

    this.resilienceBtn?.addEventListener('click', () => {
      this.send({ action: 'scenario', name: 'resilience_test' });
      flash(this.resilienceBtn);
      this.toasts.show('Resilience Test — faults scheduled, recover cleanly', 'warn');
    });

    this.soundBtn?.addEventListener('click', () => {
      const on = this.onSound?.() ?? false;
      this.app?.classList.toggle('is-sound', on);
      this.soundBtn.classList.toggle('is-active', on);
      this.soundBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      this.toasts.show(on ? 'Sound on' : 'Sound off');
    });

    this.resetBtn?.addEventListener('click', () => {
      this.send({ action: 'reset' });
      flash(this.resetBtn);
      this.toasts.show('Simulation reset');
    });

    this.dockCollapse?.addEventListener('click', () => this.toggleDock());
    const stored = localStorage.getItem('robofleet.dockCollapsed');
    this.setDockCollapsed(stored === '1');

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
        this.setTool(this.tool === 'jam' ? 'none' : 'jam');
      } else if (event.key === 'r' || event.key === 'R') {
        this.setTool(this.tool === 'rush' ? 'none' : 'rush');
      } else if (event.key === 'o' || event.key === 'O') {
        this.setTool(this.tool === 'order' ? 'none' : 'order');
      } else if (event.key === 'd' || event.key === 'D') {
        this.toggleDemand();
      } else if (event.key === 'Escape') {
        if (this.tool !== 'none') this.setTool('none');
      } else if (event.key === 'b' || event.key === 'B') {
        this.burstBtn?.click();
      } else if (event.key === 'g' || event.key === 'G') {
        this.scenarioBtn?.click();
      } else if (event.key === 'm' || event.key === 'M') {
        this.soundBtn?.click();
      } else if (event.key === 'h' || event.key === 'H') {
        this.toggleDock();
      }
    });
  }

  setTool(tool) {
    this.tool = tool;
    this.jamBtn?.classList.toggle('is-active', tool === 'jam');
    this.rushBtn?.classList.toggle('is-active', tool === 'rush');
    this.orderBtn?.classList.toggle('is-active', tool === 'order');
    if (this.jamHint) this.jamHint.hidden = tool !== 'jam';
    if (this.rushHint) this.rushHint.hidden = tool !== 'rush';
    this.setOrderHint(tool === 'order' ? 'pick' : null);
    this.onTool?.(tool);
    if (tool === 'jam') this.toasts.show('Jam mode — click a cell', 'warn');
    if (tool === 'rush') this.toasts.show('Rush mode — click a pick slot', 'good');
    if (tool === 'order') this.toasts.show('Order — pick slot, then dock door', 'good');
  }

  setOrderHint(step) {
    if (!this.orderHint) return;
    if (step === 'pick') {
      this.orderHint.hidden = false;
      this.orderHint.textContent = 'Click a pick slot, then a dock door';
    } else if (step === 'dock') {
      this.orderHint.hidden = false;
      this.orderHint.textContent = 'Now click the dock door it should leave from';
    } else {
      this.orderHint.hidden = true;
    }
  }

  toggleDemand() {
    this.syncDemand(!this.manualDemand);
    this.send({ action: 'demand', manual: this.manualDemand });
    flash(this.demandBtn);
    this.toasts.show(
      this.manualDemand
        ? 'You dispatch — random orders paused. Place an order (O)'
        : 'Live demand — warehouse is generating its own orders',
      this.manualDemand ? 'good' : undefined,
    );
  }

  syncDemand(manual) {
    this.manualDemand = !!manual;
    this.demandBtn?.classList.toggle('is-active', this.manualDemand);
    this.demandBtn?.setAttribute('aria-pressed', this.manualDemand ? 'true' : 'false');
    if (this.demandLabel) this.demandLabel.textContent = this.manualDemand ? 'You dispatch' : 'Live demand';
  }

  toggleDock() {
    this.setDockCollapsed(!this.dock?.classList.contains('is-collapsed'));
  }

  setDockCollapsed(collapsed) {
    const on = !!collapsed;
    this.dock?.classList.toggle('is-collapsed', on);
    this.dockCollapse?.setAttribute('aria-expanded', on ? 'false' : 'true');
    this.dockCollapse?.setAttribute('title', on ? 'Show controls (H)' : 'Hide controls (H)');
    try {
      localStorage.setItem('robofleet.dockCollapsed', on ? '1' : '0');
    } catch {
      /* ignore quota / private mode */
    }
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

  syncFleet(size) {
    if (!this.fleet || document.activeElement === this.fleet) return;
    const min = Number(this.fleet.min) || 0;
    const max = Number(this.fleet.max) || size;
    const clamped = Math.max(min, Math.min(max, size));
    if (Number(this.fleet.value) !== clamped) this.fleet.value = String(clamped);
    if (this.fleetValue.textContent !== String(size)) this.fleetValue.textContent = String(size);
  }
}

function flash(el) {
  if (!el) return;
  el.classList.remove('is-flash');
  void el.offsetWidth;
  el.classList.add('is-flash');
}
