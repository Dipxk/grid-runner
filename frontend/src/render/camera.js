/**
 * Grid <-> screen mapping.
 *
 * Default: fit the whole floor, square cells, centred.
 * Follow: when a robot is selected the camera eases in and tracks its
 * interpolated position so the floor reads like a stage, not a spreadsheet.
 */

export class Camera {
  constructor() {
    this.cell = 20;
    this.originX = 0;
    this.originY = 0;
    this.viewW = 0;
    this.viewH = 0;
    this.gridW = 1;
    this.gridH = 1;
    this.follow = 0;
    this._fitCell = 20;
  }

  fit(viewW, viewH, gridW, gridH, padding = 26) {
    this.viewW = viewW;
    this.viewH = viewH;
    this.gridW = gridW;
    this.gridH = gridH;
    const usableW = Math.max(40, viewW - padding * 2);
    const usableH = Math.max(40, viewH - padding * 2 - 42);
    this._fitCell = Math.max(6, Math.min(usableW / gridW, usableH / gridH));
    this.cell = this._fitCell;
    this.originX = (viewW - gridW * this.cell) / 2;
    this.originY = (viewH - 42 - gridH * this.cell) / 2 + 10;
    return this;
  }

  /**
   * Ease toward a follow target (fractional grid coords) or back to fit.
   * @param {number} dt
   * @param {[number, number]|null} target
   */
  advance(dt, target) {
    const goal = target ? 1 : 0;
    const k = 1 - Math.exp(-(dt || 16) / 160);
    this.follow += (goal - this.follow) * k;
    if (this.follow < 0.008 && !target) this.follow = 0;

    const zoom = 1 + this.follow * 0.82;
    this.cell = this._fitCell * zoom;
    const fitOX = (this.viewW - this.gridW * this.cell) / 2;
    const fitOY = (this.viewH - 42 - this.gridH * this.cell) / 2 + 10;

    if (target && this.follow > 0.01) {
      const wantX = this.viewW * 0.52 - (target[0] + 0.5) * this.cell;
      const wantY = this.viewH * 0.46 - (target[1] + 0.5) * this.cell;
      this.originX = fitOX + (wantX - fitOX) * this.follow;
      this.originY = fitOY + (wantY - fitOY) * this.follow;
    } else {
      this.originX = fitOX;
      this.originY = fitOY;
    }
  }

  cellToPx(x, y) {
    return [this.originX + x * this.cell, this.originY + y * this.cell];
  }

  centerToPx(x, y) {
    return [
      this.originX + (x + 0.5) * this.cell,
      this.originY + (y + 0.5) * this.cell,
    ];
  }

  pxToCell(px, py) {
    return [
      Math.floor((px - this.originX) / this.cell),
      Math.floor((py - this.originY) / this.cell),
    ];
  }
}
