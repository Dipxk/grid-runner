/**
 * Static warehouse floor. Drawn into an offscreen canvas and blitted each
 * frame. Shelves are extruded 2.5D blocks with carton inventory so the floor
 * reads as a live DC, not a flat grid. Hit-testing stays 2D: the extrusion
 * never leaves the shelf cell, so aisles stay clickable.
 */

import { CELL_TYPE, FLOOR } from '../theme.js';

const CARTON = ['#c4a574', '#8b9aa4', '#d7c4a0', '#6d7f6c', '#b08968', '#9a7b62'];

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
    const key = `${world.width}x${world.height}:${camera.cell.toFixed(2)}:${camera.originX.toFixed(1)}:${camera.originY.toFixed(1)}:${dpr}:${cellsFingerprint(world.cells)}`;
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
    this.#drawAisleMarks(ctx, camera, grid, cell);
    this.#drawPickSlots(ctx, camera, grid, cell);
    this.#drawDocks(ctx, camera, grid, cell);
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
  }

  #drawAisleMarks(ctx, camera, grid, cell) {
    const H = grid.length;
    const W = grid[0].length;
    const isShelf = (x, y) => y >= 0 && y < H && x >= 0 && x < W && grid[y][x] === CELL_TYPE.SHELF;
    let aisle = 0;

    for (let y = 0; y < H; y++) {
      let walk = 0;
      for (let x = 0; x < W; x++) if (grid[y][x] !== CELL_TYPE.SHELF) walk++;
      const betweenRacks = isShelfRow(grid, y - 1) || isShelfRow(grid, y + 1);
      if (walk < W * 0.55 || !betweenRacks) continue;

      const [x0, y0] = camera.cellToPx(0, y);
      ctx.save();
      ctx.strokeStyle = 'rgba(212, 175, 55, 0.45)';
      ctx.lineWidth = Math.max(1, cell * 0.06);
      ctx.setLineDash([cell * 0.35, cell * 0.28]);
      ctx.beginPath();
      ctx.moveTo(x0 + cell * 1.2, y0 + cell * 0.5);
      ctx.lineTo(x0 + W * cell - cell * 1.2, y0 + cell * 0.5);
      ctx.stroke();
      ctx.setLineDash([]);

      if (cell >= 14) {
        const letter = String.fromCharCode(65 + (aisle % 26));
        ctx.fillStyle = 'rgba(37, 56, 65, 0.42)';
        ctx.font = `600 ${Math.max(9, Math.round(cell * 0.32))}px "IBM Plex Mono", monospace`;
        ctx.textAlign = 'left';
        ctx.fillText(`AISLE ${letter}`, x0 + cell * 0.2, y0 - cell * 0.08);
      }
      aisle++;
      ctx.restore();
    }
  }

  #drawPickSlots(ctx, camera, grid, cell) {
    const H = grid.length;
    const W = grid[0].length;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (grid[y][x] !== CELL_TYPE.PICKUP) continue;
        const [px, py] = camera.cellToPx(x, y);
        const towardRight = x + 1 < W && grid[y][x + 1] === CELL_TYPE.SHELF;

        ctx.fillStyle = '#dfe8e6';
        ctx.fillRect(px + 1, py + 1, cell - 2, cell - 2);

        // Hazard tape pointing at the rack this slot serves.
        ctx.save();
        ctx.translate(px + cell / 2, py + cell / 2);
        ctx.rotate(towardRight ? 0 : Math.PI);
        ctx.fillStyle = '#e0b025';
        ctx.fillRect(-cell * 0.32, -cell * 0.07, cell * 0.4, cell * 0.14);
        ctx.fillStyle = '#1a2428';
        ctx.beginPath();
        ctx.moveTo(cell * 0.08, -cell * 0.16);
        ctx.lineTo(cell * 0.34, 0);
        ctx.lineTo(cell * 0.08, cell * 0.16);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // Put-to-light bezel (the LED itself is drawn live in scene.js).
        const lx = towardRight ? px + cell * 0.16 : px + cell * 0.84;
        const ly = py + cell * 0.22;
        ctx.fillStyle = '#1c2a30';
        ctx.beginPath();
        ctx.arc(lx, ly, Math.max(2, cell * 0.08), 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#3d5858';
        ctx.beginPath();
        ctx.arc(lx, ly, Math.max(1.2, cell * 0.045), 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  #drawDocks(ctx, camera, grid, cell) {
    const H = grid.length;
    const W = grid[0].length;
    let bay = 0;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (grid[y][x] !== CELL_TYPE.DROPOFF) continue;
        const [px, py] = camera.cellToPx(x, y);
        bay += 1;

        ctx.fillStyle = '#e8d7b8';
        ctx.fillRect(px + 1, py + 1, cell - 2, cell - 2);

        // Rubber dock bumpers.
        ctx.fillStyle = '#8a5a28';
        ctx.fillRect(px + cell * 0.12, py + cell * 0.72, cell * 0.76, cell * 0.14);

        // 2.5D door frame sitting on the stall.
        const d = cell * 0.34;
        ctx.fillStyle = '#6b5340';
        ctx.fillRect(px + cell * 0.1, py + cell * 0.08, cell * 0.12, cell * 0.62);
        ctx.fillRect(px + cell * 0.78, py + cell * 0.08, cell * 0.12, cell * 0.62);
        ctx.fillStyle = '#8a6a4e';
        ctx.fillRect(px + cell * 0.1, py + cell * 0.04, cell * 0.8, cell * 0.12);

        // Recessed door (darker = interior).
        ctx.fillStyle = '#2a3338';
        ctx.fillRect(px + cell * 0.24, py + cell * 0.18, cell * 0.52, cell * 0.5 + d * 0.15);

        if (cell >= 13) {
          ctx.fillStyle = 'rgba(37, 56, 65, 0.7)';
          ctx.font = `600 ${Math.max(8, Math.round(cell * 0.28))}px "IBM Plex Mono", monospace`;
          ctx.textAlign = 'center';
          ctx.fillText(`DOOR ${String(bay).padStart(2, '0')}`, px + cell / 2, py - cell * 0.1);
        }
      }
    }
  }

  #drawShelves(ctx, camera, grid, cell) {
    const H = grid.length;
    const W = grid[0].length;
    const isShelf = (x, y) => x >= 0 && y >= 0 && x < W && y < H && grid[y][x] === CELL_TYPE.SHELF;

    // Back-to-front so south faces of northern racks sit behind southern ones.
    for (let y = 0; y < H; y++) {
      let x = 0;
      while (x < W) {
        if (!isShelf(x, y)) {
          x++;
          continue;
        }
        let x1 = x;
        while (x1 < W && isShelf(x1, y)) x1++;
        this.#drawRack(ctx, camera, cell, x, y, x1 - x);
        x = x1;
      }
    }
  }

  #drawRack(ctx, camera, cell, x, y, span) {
    const [px, py] = camera.cellToPx(x, y);
    const w = span * cell;
    const h = cell;
    const side = Math.max(3, cell * 0.28);

    // East face (right bevel).
    ctx.fillStyle = '#1a262c';
    ctx.beginPath();
    ctx.moveTo(px + w, py);
    ctx.lineTo(px + w, py + h - side);
    ctx.lineTo(px + w - side * 0.35, py + h);
    ctx.lineTo(px + w - side * 0.35, py + side);
    ctx.closePath();
    ctx.fill();

    // South face (front of the rack — this is the 3D).
    ctx.fillStyle = '#1e2c33';
    ctx.fillRect(px, py + h - side, w - side * 0.35, side);

    // Top deck.
    ctx.fillStyle = FLOOR.shelf;
    ctx.fillRect(px, py, w - side * 0.35, h - side);

    // Uprights.
    ctx.fillStyle = '#151f24';
    ctx.fillRect(px, py, Math.max(1.5, cell * 0.06), h - side * 0.2);
    ctx.fillRect(px + w - side * 0.35 - Math.max(1.5, cell * 0.06), py, Math.max(1.5, cell * 0.06), h - side * 0.2);

    // Beam slats (two shelf levels).
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineWidth = Math.max(1, cell * 0.045);
    ctx.beginPath();
    for (let k = 1; k <= 2; k++) {
      const yy = py + ((h - side) * k) / 3;
      ctx.moveTo(px + cell * 0.08, yy);
      ctx.lineTo(px + w - side * 0.35 - cell * 0.08, yy);
    }
    ctx.stroke();

    // Cartons sitting on the beams.
    const boxH = (h - side) * 0.22;
    const boxW = cell * 0.38;
    for (let i = 0; i < span; i++) {
      const n = 1 + ((x + i + y) % 3 === 0 ? 1 : 0);
      for (let b = 0; b < n; b++) {
        const bx = px + i * cell + cell * (0.14 + b * 0.4);
        const by = py + (h - side) * (0.18 + ((x + i + b) % 2) * 0.28);
        ctx.fillStyle = CARTON[(x * 7 + y * 3 + i + b) % CARTON.length];
        ctx.fillRect(bx, by, boxW, boxH);
        ctx.strokeStyle = 'rgba(20, 24, 26, 0.35)';
        ctx.lineWidth = 0.8;
        ctx.strokeRect(bx + 0.4, by + 0.4, boxW - 0.8, boxH - 0.8);
        ctx.fillStyle = 'rgba(255, 255, 255, 0.18)';
        ctx.fillRect(bx + boxW * 0.15, by + 1, boxW * 0.7, Math.max(1, boxH * 0.18));
      }
    }

    if (span >= 3 && cell >= 16) {
      const bay = aisleBay(x, y);
      ctx.fillStyle = 'rgba(232, 236, 235, 0.55)';
      ctx.font = `600 ${Math.max(8, Math.round(cell * 0.26))}px "IBM Plex Mono", monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(bay, px + (w - side * 0.35) / 2, py + (h - side) * 0.92);
    }
  }

  #drawPerimeter(ctx, camera, world) {
    const [x0, y0] = camera.cellToPx(0, 0);
    const w = world.width * camera.cell;
    const h = world.height * camera.cell;
    ctx.strokeStyle = FLOOR.border;
    ctx.lineWidth = 2;
    ctx.strokeRect(x0 - 1, y0 - 1, w + 2, h + 2);

    if (camera.cell >= 12) {
      ctx.fillStyle = 'rgba(37, 56, 65, 0.35)';
      ctx.font = `600 ${Math.max(9, Math.round(camera.cell * 0.3))}px "IBM Plex Mono", monospace`;
      ctx.textAlign = 'left';
      ctx.fillText('PICK MODULE', x0 + 4, y0 - 6);
      ctx.textAlign = 'right';
      ctx.fillText('OUTBOUND', x0 + w - 4, y0 + h + camera.cell * 0.45);
    }
  }
}

function cellsFingerprint(cells) {
  if (!cells || !cells.length) return '0';
  const joined = typeof cells[0] === 'string' ? cells.join('') : String(cells.length);
  let h = 0;
  for (let i = 0; i < joined.length; i++) {
    h = (Math.imul(h, 31) + joined.charCodeAt(i)) | 0;
  }
  return `${joined.length}:${h}`;
}

function isShelfRow(grid, y) {
  if (y < 0 || y >= grid.length) return false;
  let n = 0;
  for (const v of grid[y]) if (v === CELL_TYPE.SHELF) n++;
  return n > grid[y].length * 0.2;
}

function aisleBay(x, y) {
  const col = String(x + 1).padStart(2, '0');
  const row = String.fromCharCode(65 + (y % 26));
  return `${row}-${col}`;
}
