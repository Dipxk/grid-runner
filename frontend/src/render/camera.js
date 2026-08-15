/**
 * Grid <-> screen mapping. Keeps square cells, fits the whole floor in view
 * and centres it, so the layout never feels cramped or lopsided when the
 * window is resized.
 */

export class Camera {
  constructor() {
    this.cell = 20;
    this.originX = 0;
    this.originY = 0;
    this.viewW = 0;
    this.viewH = 0;
  }

  fit(viewW, viewH, gridW, gridH, padding = 26) {
    this.viewW = viewW;
    this.viewH = viewH;
    const usableW = Math.max(40, viewW - padding * 2);
    const usableH = Math.max(40, viewH - padding * 2 - 42); // room for the dock
    this.cell = Math.max(6, Math.min(usableW / gridW, usableH / gridH));
    this.originX = (viewW - gridW * this.cell) / 2;
    this.originY = (viewH - 42 - gridH * this.cell) / 2 + 10;
    return this;
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
