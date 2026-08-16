/**
 * Tiny Web Audio bed. Mute by default — sound only after an explicit click,
 * which also satisfies the browser autoplay policy.
 */

export class SoundBed {
  constructor() {
    this.enabled = false;
    /** @type {AudioContext|null} */
    this.ctx = null;
  }

  toggle() {
    this.enabled = !this.enabled;
    if (this.enabled) this.#ensure();
    else if (this.ctx && this.ctx.state === 'running') this.ctx.suspend();
    return this.enabled;
  }

  delivered() {
    this.#tone(880, 0.09, 'triangle', 0.08);
    this.#tone(1320, 0.07, 'sine', 0.04, 0.05);
  }

  picked() {
    this.#tone(520, 0.06, 'sine', 0.05);
  }

  jam() {
    this.#noise(0.14, 0.1);
    this.#tone(140, 0.18, 'sawtooth', 0.05);
  }

  rush() {
    this.#tone(660, 0.08, 'square', 0.04);
    this.#tone(990, 0.1, 'square', 0.03, 0.06);
  }

  scenarioStart() {
    this.#tone(392, 0.12, 'triangle', 0.07);
    this.#tone(523, 0.14, 'triangle', 0.06, 0.1);
    this.#tone(659, 0.18, 'triangle', 0.05, 0.22);
  }

  scenarioOver(grade) {
    if (grade === 'S' || grade === 'A') {
      this.#tone(523, 0.12, 'triangle', 0.07);
      this.#tone(784, 0.22, 'triangle', 0.08, 0.1);
    } else {
      this.#tone(330, 0.2, 'sine', 0.07);
    }
  }

  #ensure() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!this.ctx) this.ctx = new AC();
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  }

  #tone(freq, dur, type, gain, delay = 0) {
    if (!this.enabled) return;
    const ctx = this.#ensure();
    if (!ctx) return;
    const t0 = ctx.currentTime + delay;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(gain, t0 + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g);
    g.connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }

  #noise(dur, gain) {
    if (!this.enabled) return;
    const ctx = this.#ensure();
    if (!ctx) return;
    const n = Math.floor(ctx.sampleRate * dur);
    const buffer = ctx.createBuffer(1, n, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < n; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / n);
    const src = ctx.createBufferSource();
    const g = ctx.createGain();
    src.buffer = buffer;
    g.gain.value = gain;
    src.connect(g);
    g.connect(ctx.destination);
    src.start();
  }
}
