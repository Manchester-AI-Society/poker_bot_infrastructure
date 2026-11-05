// Chart building blocks. The colour and scale functions are pure (tested in
// Node); the SVG builders need a DOM and are used by the views.

import { svg } from './dom.js';
import { fmtBB, fmtPlain, inkFor, mixHex, niceMax, quantile } from './format.js';

/** Symmetric axis limit that fits every score and its interval. */
export function scoreAxisMax(teams) {
  let widest = 0;
  for (const t of teams) {
    if (t.score == null) continue;
    widest = Math.max(widest, Math.abs(t.score) + (t.ci95 ?? 0));
  }
  return niceMax(Math.max(widest, 0.1));
}

/**
 * Colours for one head-to-head cell. `value` is the row team's mean bb/hand
 * against the column team, `ci` its 95% half-width. Cells whose interval
 * reaches zero are faded: the result is not statistically clear.
 */
export function cellColors(value, ci, max, tokens) {
  if (value == null) return null;
  const clear = ci != null && Math.abs(value) > ci;
  let strength = Math.min(1, Math.abs(value) / max);
  strength = 0.85 * Math.pow(strength, 0.8);
  if (!clear) strength *= 0.4;
  const pole = value >= 0 ? tokens.pos : tokens.neg;
  const bg = mixHex(tokens.mid, pole, strength);
  return { bg, fg: inkFor(bg), clear };
}

/** A matrix scale that one outlier cannot wash out. */
export function matrixMax(values) {
  const magnitudes = values.filter(Number.isFinite).map(Math.abs);
  return niceMax(Math.max(quantile(magnitudes, 0.9), 0.25));
}

const X_PAD = 8;

function scaleX(value, max, width) {
  const inner = width - 2 * X_PAD;
  return X_PAD + ((value + max) / (2 * max)) * inner;
}

/**
 * One row of the leaderboard plot: a thin interval line, a dot at the score
 * and a zero baseline, on a scale shared by every row.
 */
export function ciPlot({ score, ci, max, width = 260, height = 30, label }) {
  const mid = height / 2;
  const children = [
    svg('title', {}, label),
    svg('line', {
      x1: scaleX(-max, max, width), x2: scaleX(max, max, width),
      y1: mid, y2: mid, stroke: 'var(--grid)', 'stroke-width': 1,
    }),
    svg('line', {
      x1: scaleX(0, max, width), x2: scaleX(0, max, width),
      y1: 3, y2: height - 3, stroke: 'var(--axis)', 'stroke-width': 1,
    }),
  ];
  if (score != null) {
    if (ci != null && ci > 0) {
      const lo = scaleX(Math.max(-max, score - ci), max, width);
      const hi = scaleX(Math.min(max, score + ci), max, width);
      children.push(
        svg('line', {
          x1: lo, x2: hi, y1: mid, y2: mid,
          stroke: 'var(--series)', 'stroke-width': 2, 'stroke-linecap': 'round',
        }),
        svg('line', { x1: lo, x2: lo, y1: mid - 4, y2: mid + 4, stroke: 'var(--series)', 'stroke-width': 2 }),
        svg('line', { x1: hi, x2: hi, y1: mid - 4, y2: mid + 4, stroke: 'var(--series)', 'stroke-width': 2 }),
      );
    }
    children.push(
      svg('circle', {
        cx: scaleX(Math.max(-max, Math.min(max, score)), max, width), cy: mid, r: 5,
        fill: 'var(--series)', stroke: 'var(--surface)', 'stroke-width': 2,
      }),
    );
  }
  return svg(
    'svg',
    {
      viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': label,
      preserveAspectRatio: 'none',
    },
    ...children,
  );
}

/** The shared axis drawn above the plot column: -max, 0, +max. */
export function axisHeader({ max, width = 260, height = 18 }) {
  const tick = (value, anchor) =>
    svg(
      'text',
      {
        x: scaleX(value, max, width), y: height - 4, 'text-anchor': anchor,
        class: 'axis-label',
      },
      value === 0 ? '0' : fmtBB(value, max < 1 ? 2 : 1),
    );
  return svg(
    'svg',
    { viewBox: `0 0 ${width} ${height}`, 'aria-hidden': 'true', preserveAspectRatio: 'none' },
    tick(-max, 'start'),
    tick(0, 'middle'),
    tick(max, 'end'),
  );
}

export function describeScore(team) {
  if (team.score == null) return `${team.team}: no results yet`;
  const half = team.ci95 == null ? 'interval unknown' : `± ${fmtPlain(team.ci95)}`;
  return `${team.team}: ${fmtBB(team.score)} bb/hand, ${half} (95% interval)`;
}
