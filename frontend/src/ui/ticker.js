/** Live ops ticker — recent picks, docks, jams. Business-readable, not debug. */

const MAX = 4;

export class OpsTicker {
  constructor(root = document) {
    this.track = root.querySelector('#ticker-track');
    this.lines = [];
  }

  push(text, tone = 'neutral') {
    if (!this.track) return;
    const t = new Date();
    const stamp = `${pad(t.getHours())}:${pad(t.getMinutes())}:${pad(t.getSeconds())}`;
    this.lines.unshift({ stamp, text, tone });
    if (this.lines.length > MAX) this.lines.pop();
    this.#render();
  }

  #render() {
    this.track.replaceChildren();
    for (const line of this.lines) {
      const el = document.createElement('div');
      el.className = 'ticker__line';
      el.dataset.tone = line.tone;
      el.innerHTML = `<span class="ticker__time">${line.stamp}</span> ${escapeHtml(line.text)}`;
      this.track.appendChild(el);
    }
  }
}

function pad(n) {
  return String(n).padStart(2, '0');
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
