// Where the seats go round a poker table, for 2 to 23 players. Pure (no DOM),
// so Node can check that nothing overlaps or leaves the box at any size.
//
// The table is an oval box W x H (pixels). Seat i sits on an ellipse inside
// it, starting at the bottom and going round clockwise (the order of play).
// Bigger seats are tried first; when no size fits the box without covering
// the middle (where the board and the pot go) or each other, the answer is a
// plain list of seats instead of a ring (narrow screens, many players).

/** Seat sizes in pixels at scale 1, largest first. `font` is the seat's text size. */
export const SIZES = [
  { name: 'xl', w: 184, h: 100, font: 15 },
  { name: 'l', w: 150, h: 84, font: 13 },
  { name: 'm', w: 124, h: 74, font: 12 },
  { name: 's', w: 104, h: 64, font: 11 },
  { name: 'xs', w: 88, h: 56, font: 10 },
];

/** Height of the oval as a fraction of its width, tried in this order. */
const RATIOS = [0.5, 0.58, 0.68, 0.8, 0.92, 1.04, 1.2];
const GAP = 4;
const PADDING = 2;
/** The middle must stay free for this much (scale 1): the board, the pot, the status line. */
const CENTER = { w: 214, h: 118 };
const CENTER_NARROW = { w: 176, h: 118 };
/** The widest a ring is drawn (by seat count), so two seats do not sit a screen apart. */
export function maxRingWidth(count) {
  return count <= 8 ? 900 : count <= 14 ? 1040 : 1200;
}

/** Centres of `count` seats on the ellipse that fits seats of size (w, h) in a W x H box. */
export function ringPositions(count, W, H, w, h) {
  const rx = (W - w) / 2 - PADDING;
  const ry = (H - h) / 2 - PADDING;
  const out = [];
  for (let i = 0; i < count; i += 1) {
    const angle = Math.PI / 2 + (i * 2 * Math.PI) / count;
    out.push({ x: W / 2 + rx * Math.cos(angle), y: H / 2 + ry * Math.sin(angle) });
  }
  return out;
}

const rect = (p, w, h) => ({ l: p.x - w / 2, r: p.x + w / 2, t: p.y - h / 2, b: p.y + h / 2 });
const apart = (a, b, gap) => a.r + gap <= b.l || b.r + gap <= a.l || a.b + gap <= b.t || b.b + gap <= a.t;

/** True when the seats overlap each other, leave the box, or cover the middle. */
export function collides(positions, W, H, w, h, center) {
  const boxes = positions.map((p) => rect(p, w, h));
  for (const box of boxes) {
    if (box.l < 0 || box.t < 0 || box.r > W || box.b > H) return true;
  }
  const middle = rect({ x: W / 2, y: H / 2 }, center.w, center.h);
  for (const box of boxes) if (!apart(box, middle, 0)) return true;
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) if (!apart(boxes[i], boxes[j], GAP)) return true;
  }
  return false;
}

/**
 * How to lay out `count` seats in a box `width` pixels wide.
 * `scale` grows everything for big screens (the TV view).
 * Returns {mode: 'ring', size, W, H, positions: [{x, y}]} or {mode: 'list', size}.
 */
export function chooseLayout(count, width, scale = 1) {
  const n = Math.max(1, count);
  const W = Math.floor(Math.min(width, maxRingWidth(n) * scale));
  const narrow = W < 520 * scale;
  const center = narrow ? CENTER_NARROW : CENTER;
  const need = { w: center.w * scale, h: center.h * scale };
  // On a wide screen a squarer table with smaller seats beats a very tall one.
  const passes = narrow ? [RATIOS] : [RATIOS.filter((r) => r <= 1.04), RATIOS];
  // The smallest seats are hard to read on a phone: a list is better there.
  const sizes = narrow ? SIZES.slice(1, 4) : SIZES;
  for (const ratios of passes) {
    for (const size of sizes) {
      const w = size.w * scale;
      const h = size.h * scale;
      for (const ratio of ratios) {
        const H = Math.round(W * ratio);
        const positions = ringPositions(n, W, H, w, h);
        if (!collides(positions, W, H, w, h, need)) {
          return { mode: 'ring', size: { ...size, w, h, font: size.font * scale }, W, H, positions };
        }
      }
    }
  }
  // A list has room for readable type.
  return { mode: 'list', size: { name: 'list', w: 150 * scale, h: 70 * scale, font: 12 * scale } };
}
