/**
 * Single source of truth for colour and geometry used by the canvas renderer.
 * The same ramp is mirrored in styles.css so the legend, the pills and the
 * robots on the floor can never drift apart.
 */

export const STATUS_COLORS = {
  idle: '#8496a0',
  to_pickup: '#12857a',
  carrying: '#d5872a',
  rerouting: '#cf5137',
};

export const STATUS_DARK = {
  idle: '#5d6f79',
  to_pickup: '#0a5d55',
  carrying: '#a1621a',
  rerouting: '#96331f',
};

export const STATUS_LABELS = {
  idle: 'idle',
  to_pickup: 'to pickup',
  carrying: 'carrying',
  rerouting: 'rerouting',
};

export const FLOOR = {
  base: '#e9eeed',
  baseAlt: '#e4eae9',
  grid: 'rgba(37, 56, 65, 0.055)',
  gridMajor: 'rgba(37, 56, 65, 0.10)',
  shelf: '#253841',
  shelfEdge: '#1a2930',
  shelfSlat: 'rgba(255, 255, 255, 0.07)',
  pickFill: '#d3e6e2',
  pickLine: '#12857a',
  dropFill: '#f4e3c8',
  dropLine: '#d5872a',
  chargerLine: 'rgba(77, 98, 108, 0.45)',
  border: 'rgba(37, 56, 65, 0.20)',
};

export const JAM = {
  fill: 'rgba(207, 81, 55, 0.30)',
  stripe: 'rgba(207, 81, 55, 0.62)',
  edge: '#b8371f',
};

export const CELL_TYPE = {
  FLOOR: 0,
  SHELF: 1,
  PICKUP: 2,
  DROPOFF: 3,
  CHARGER: 4,
};

export function statusColor(status) {
  return STATUS_COLORS[status] || STATUS_COLORS.idle;
}

export function statusDark(status) {
  return STATUS_DARK[status] || STATUS_DARK.idle;
}
