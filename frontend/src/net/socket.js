/**
 * WebSocket transport with automatic reconnect and exponential backoff.
 *
 * The socket is intentionally dumb: it hands raw messages to callbacks and
 * knows nothing about simulation semantics. All interpretation happens in
 * state/tickBuffer.js and the UI modules.
 */

export class SimSocket {
  /**
   * @param {object} handlers
   * @param {(msg:object)=>void} handlers.onInit
   * @param {(msg:object)=>void} handlers.onTick
   * @param {(msg:object)=>void} [handlers.onAck]
   * @param {(state:'connecting'|'live'|'offline')=>void} [handlers.onStatus]
   */
  constructor(handlers) {
    this.handlers = handlers;
    this.ws = null;
    this.retries = 0;
    this.closed = false;
    this.queue = [];
  }

  url() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/ws`;
  }

  connect() {
    this.closed = false;
    this.setStatus('connecting');
    const ws = new WebSocket(this.url());
    this.ws = ws;

    ws.addEventListener('open', () => {
      this.retries = 0;
      this.setStatus('live');
      for (const msg of this.queue.splice(0)) ws.send(msg);
    });

    ws.addEventListener('message', (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === 'init') this.handlers.onInit?.(msg);
      else if (msg.type === 'tick') this.handlers.onTick?.(msg);
      else if (msg.type === 'ack') this.handlers.onAck?.(msg);
    });

    const retry = () => {
      if (this.closed) return;
      this.setStatus('offline');
      const delay = Math.min(8000, 400 * 2 ** this.retries++);
      setTimeout(() => this.connect(), delay);
    };

    ws.addEventListener('close', retry);
    ws.addEventListener('error', () => ws.close());
  }

  setStatus(state) {
    this.handlers.onStatus?.(state);
  }

  /** Send a control command; queued if the socket is still connecting. */
  send(payload) {
    const msg = JSON.stringify(payload);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(msg);
    else this.queue.push(msg);
  }

  close() {
    this.closed = true;
    this.ws?.close();
  }
}
