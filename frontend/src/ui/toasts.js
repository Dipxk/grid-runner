/** Transient confirmations so every control press has a visible consequence. */

export class Toasts {
  constructor(container) {
    this.container = container;
  }

  show(text, tone = 'neutral', ttl = 2000) {
    if (!this.container) return;
    const el = document.createElement('div');
    el.className = 'toast';
    el.dataset.tone = tone;
    el.textContent = text;
    this.container.appendChild(el);
    setTimeout(() => {
      el.classList.add('is-out');
      setTimeout(() => el.remove(), 240);
    }, ttl);
    // Never stack more than three.
    while (this.container.children.length > 3) this.container.firstChild.remove();
  }
}
