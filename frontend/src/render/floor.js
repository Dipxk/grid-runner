/**
 * Static warehouse floor plan, rendered once into an offscreen canvas and
 * blitted every frame. Redrawn only on resize or world change.
 *
 * Everything here is about making the grid read as a *warehouse* rather than
 * a debug lattice: shelf blocks are merged into solid racks with slat detail
 * and outlined edges, pick faces get a directional marker pointing at the
 * rack they serve, and dropoff stations get chevrons and a bay label.
 */

import { CELL_TYPE, FLOOR } from '../theme.js';

export class FloorRenderer {
  constructor() {
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d');
    this.key = '';
  }

  /**
   * @param {{width:number,height:number,cells:string[]}} world
   * @param {import('./camera.js').Camera} camera
   */
  render(world, camera, dpr) {
    const key = `${world.width}x${world.height}:${camera.cell.toFixed(2)}:${camera.originX.toFixed(1)}:${camera.originY.toFixed(1)}:${dpr}`;
    if (key === this.key) return this.canvas;
    this.key = key;

    const w = Math.max(1, Math.ceil(camera.viewW * dpr));
    const h = Math.max(1, Math.ceil(camera.viewH * dpr));
    this.canvas.width = w;
    this.canvas.height = h;

    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, camera.viewW, camera.viewH);

    const cell = camera.cell;
    const grid = world.cells.map((row) => row.split('').map(Number));

    this.#drawSlab(ctx, camera, world);
    this.#drawGrid(ctx, camera, world, cell);
    this.#drawStations(ctx, camera, grid, cell);
    this.#drawShelves(ctx, camera, grid, cell);
    this.#drawPerimeter(ctx, camera, world);

    return this.canvas;
  }

  #drawSlab(ctx, camera, world) {
    const [x0, y0] = camera.cellToPx(0, 0);
    const w = world.width * camera.cell;
    const h = world.height * camera.cell;

    const grad = ctx.createLinearGradient(x0, y0, x0 + w, y0 + h);
    grad.addColorStop(0, '#eef2f1');
    grad.addColorStop(0.55, FLOOR.base);
    grad.addColorStop(1, FLOOR.baseAlt);
    ctx.fillStyle = grad;
    ctx.fillRect(x0, y0, w, h);
  }

  #drawGrid(ctx, camera, world, cell) {
    const [x0, y0] = camera.cellToPx(0, 0);
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x <= world.width; x++) {
      const px = Math.round(x0 + x * cell) + 0.5;
      ctx.moveTo(px, y0);
      ctx.lineTo(px, y0 + world.height * cell);
    }
    for (let y = 0; y <= world.height; y++) {
      const py = Math.round(y0 + y * cell) + 0.5;
      ctx.moveTo(x0, py);
      ctx.lineTo(x0 + world.width * cell, py);
    }
    ctx.strokeStyle = FLOOR.grid;
    ctx.stroke();

    // Major lines every 5 cells give the eye a sense of scale.
    ctx.beginPath();
    for (let x = 0; x <= world.width; x += 5) {
      const px = Math.round(x0 + x * cell) + 0.5;
      ctx.moveTo(px, y0);
      ctx.lineTo(px, y0 + world.height * cell);
    }
    for (let y = 0; y <= world.height; y += 5) {
      const py = Math.round(y0 + y * cell) + 0.5;
      ctx.moveTo(x0, py);
      ctx.lineTo(x0 + world.width * cell, py);
    }
    ctx.strokeStyle = FLOOR.gridMajor;
    ctx.stroke();
  }

  #drawShelves(ctx, camera, grid, cell) {
    const H = grid.length;
    const W = grid[0].length;
    const isShelf = (x, y) => x >= 0 && y >= 0 && x < W && y < H && grid[y][x] === CELL_TYPE.SHELF;

    // Bodies first so the outline pass sits on top of every block.
    ctx.fillStyle = FLOOR.shelf;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!isShelf(x, y)) continue;
        const [px, py] = camera.cellToPx(x, y);
        ctx.fillRect(px, py, cell + 0.6, cell + 0.6);
      }
    }

    // Rack slats: horizontal highlights that read as shelving levels.
    ctx.strokeStyle = FLOOR.shelfSlat;
    ctx.lineWidth = Math.max(1, cell * 0.05);
    ctx.beginPath();
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!isShelf(x, y)) continue;
        const [px, py] = camera.cellToPx(x, y);
        for (let k = 1; k <= 2; k++) {
          const yy = py + (cell * k) / 3;
          ctx.moveTo(px + cell * 0.14, yy);
          ctx.lineTo(px + cell * 0.86, yy);
        }
      }
    }
    ctx.stroke();

    // Outline only the outer edges of each contiguous block.
    ctx.strokeStyle = FLOOR.shelfEdge;
    ctx.lineWidth = Math.max(1, cell * 0.07);
    ctx.beginPath();
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!isShelf(x, y)) continue;
        const [px, py] = camera.cellToPx(x, y);
        if (!isShelf(x, y - 1)) { ctx.moveTo(px, py); ctx.lineTo(px + cell, py); }
        if (!isShelf(x, y + 1)) { ctx.moveTo(px, py + cell); ctx.lineTo(px + cell, py + cell); }
        if (!isShelf(x - 1, y)) { ctx.moveTo(px, py); ctx.lineTo(px, py + cell); }
        if (!isShelf(x + 1, y)) { ctx.moveTo(px + cell, py); ctx.lineTo(px + cell, py + cell); }
      }
    }
    ctx.stroke();
  }

  #drawStations(ctx, camera, grid, cell) {
    const H = grid.length;
    const W = grid[0].length;
    let bay = 0;

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const type = grid[y][x];
        if (type === CELL_TYPE.FLOOR || type === CELL_TYPE.SHELF) continue;
        const [px, py] = camera.cellToPx(x, y);

        if (type === CELL_TYPE.PICKUP) {
          ctx.fillStyle = FLOOR.pickFill;
          ctx.fillRect(px + 1, py + 1, cell - 2, cell - 2);
          // Marker points toward the rack this face serves.
          const towardRight = x + 1 < W && grid[y][x + 1] === CELL_TYPE.SHELF;
          ctx.strokeStyle = FLOOR.pickLine;
          ctx.lineWidth = Math.max(1, cell * 0.09);
          ctx.beginPath();
          const cx = px + cell / 2;
          const cy = py + cell / 2;
          const r = cell * 0.19;
          const dir = towardRight ? 1 : -1;
          ctx.moveTo(cx - dir * r * 0.5, cy - r);
          ctx.lineTo(cx + dir * r * 0.7, cy);
          ctx.lineTo(cx - dir * r * 0.5, cy + r);
          ctx.stroke();
        } else if (type === CELL_TYPE.DROPOFF) {
          ctx.fillStyle = FLOOR.dropFill;
          ctx.fillRect(px + 1, py + 1, cell - 2, cell - 2);
          ctx.strokeStyle = FLOOR.dropLine;
          ctx.lineWidth = Math.max(1, cell * 0.08);
          ctx.strokeRect(px + 1.5, py + 1.5, cell - 3, cell - 3);
          ctx.beginPath();
          for (let k = 0; k < 2; k++) {
            const yy = py + cell * (0.36 + k * 0.26);
            ctx.moveTo(px + cell * 0.28, yy - cell * 0.08);
            ctx.lineTo(px + cell * 0.5, yy + cell * 0.06);
            ctx.lineTo(px + cell * 0.72, yy - cell * 0.08);
          }
          ctx.stroke();
          if (cell >= 17) {
            ctx.fillStyle = 'rgba(37, 56, 65, 0.55)';
            ctx.font = `600 ${Math.round(cell * 0.34)}px "IBM Plex Mono", monospace`;
            ctx.textAlign = 'center';
            ctx.fillText(`D${++bay}`, px + cell / 2, py - cell * 0.18);
          }
        } else if (type === CELL_TYPE.CHARGER) {
          ctx.strokeStyle = FLOOR.chargerLine;
          ctx.lineWidth = 1.2;
          ctx.setLineDash([cell * 0.18, cell * 0.14]);
          ctx.strokeRect(px + 2, py + 2, cell - 4, cell - 4);
          ctx.setLineDash([]);
        }
      }
    }
  }

  #drawPerimeter(ctx, camera, world) {
    const [x0, y0] = camera.cellToPx(0, 0);
    const w = world.width * camera.cell;
    const h = world.height * camera.cell;
    ctx.strokeStyle = FLOOR.border;
    ctx.lineWidth = 2;
    ctx.strokeRect(x0 - 1, y0 - 1, w + 2, h + 2);
  }
}
