import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cellColors, isClipped, matrixMax, scoreAxisMax } from '../../arena/site/js/charts.js';
import {
  MINUS,
  ago,
  buildHash,
  contrast,
  fmtBB,
  fmtChips,
  fmtPlain,
  inkFor,
  mixHex,
  niceMax,
  parseHash,
  plural,
  quantile,
} from '../../arena/site/js/format.js';

test('fmtBB shows a sign and never prints negative zero', () => {
  assert.equal(fmtBB(0.1234), '+0.123');
  assert.equal(fmtBB(-0.75), `${MINUS}0.750`);
  assert.equal(fmtBB(-0.0001), '0.000');
  assert.equal(fmtBB(0), '0.000');
  assert.equal(fmtBB(null), '—');
  assert.equal(fmtBB(Infinity), '—');
  assert.equal(fmtBB(1.5, 1), '+1.5');
});

test('plain and chip formats handle missing values', () => {
  assert.equal(fmtPlain(0.04567), '0.046');
  assert.equal(fmtPlain(undefined), '—');
  assert.equal(fmtChips(1234567.4), '1,234,567');
  assert.equal(fmtChips(NaN), '—');
});

test('ago words', () => {
  assert.equal(ago(2), 'just now');
  assert.equal(ago(12), '12 s ago');
  assert.equal(ago(180), '3 min ago');
  assert.equal(ago(7300), '2 h ago');
  assert.equal(ago(200000), '2 d ago');
  assert.equal(ago(null), '');
  assert.equal(plural(1, 'team'), '1 team');
  assert.equal(plural(3, 'team'), '3 teams');
  assert.equal(plural(190, 'match'), '190 matches');
  assert.equal(plural(0, 'hand'), '0 hands');
  assert.equal(plural(1, 'match'), '1 match');
});

test('hash routes parse and rebuild', () => {
  assert.deepEqual(parseHash('#/team/alpha-1?kind=final'), {
    path: ['team', 'alpha-1'],
    query: { kind: 'final' },
  });
  assert.deepEqual(parseHash('#/'), { path: [], query: {} });
  assert.deepEqual(parseHash(''), { path: [], query: {} });
  assert.deepEqual(parseHash('#/matches?team=a%20b'), {
    path: ['matches'],
    query: { team: 'a b' },
  });
  assert.equal(buildHash(['team', 'a b']), '#/team/a%20b');
  assert.equal(buildHash(['matches'], { team: 'x', kind: '' }), '#/matches?team=x');
  // A malformed escape must not throw.
  assert.deepEqual(parseHash('#/team/%E0%A4%A').path, ['team', '%E0%A4%A']);
});

test('niceMax rounds up to a readable axis limit', () => {
  assert.equal(niceMax(0.03), 0.05);
  assert.equal(niceMax(0.7), 1);
  assert.equal(niceMax(1.2), 2);
  assert.equal(niceMax(2.3), 2.5);
  assert.equal(niceMax(4), 5);
  assert.equal(niceMax(7), 10);
  assert.equal(niceMax(0), 1);
  assert.equal(niceMax(NaN), 1);
});

test('colour mixing and text contrast', () => {
  assert.equal(mixHex('#000000', '#ffffff', 0), '#000000');
  assert.equal(mixHex('#000000', '#ffffff', 1), '#ffffff');
  assert.equal(mixHex('#000000', '#ffffff', 0.5), '#808080');
  assert.equal(mixHex('#fff', '#000', 2), '#000000'); // clamped, short hex ok
  assert.ok(contrast('#000000', '#ffffff') > 20);
  assert.equal(inkFor('#ffffff'), '#0b0b0b');
  assert.equal(inkFor('#0d366b'), '#ffffff');
});

test('quantile ignores junk and handles empty input', () => {
  assert.equal(quantile([], 0.9), 0);
  assert.equal(quantile([3, 1, 2, NaN], 0), 1);
  assert.equal(quantile([1, 2, 3, 4, 5], 1), 5);
});

const TOKENS = { pos: '#2a78d6', neg: '#e34948', mid: '#f0efec' };

test('matrix cells: sign picks the pole, an unclear result is faded', () => {
  const win = cellColors(1, 0.1, 1, TOKENS);
  const loss = cellColors(-1, 0.1, 1, TOKENS);
  const unclear = cellColors(1, 2, 1, TOKENS);

  assert.equal(win.clear, true);
  assert.equal(loss.clear, true);
  assert.equal(unclear.clear, false);
  assert.notEqual(win.bg, loss.bg);
  assert.equal(cellColors(null, null, 1, TOKENS), null);
  // Faded cells sit closer to the neutral midpoint than clear ones.
  assert.ok(contrast(unclear.bg, TOKENS.mid) < contrast(win.bg, TOKENS.mid));
});

test('matrix cell text is always readable against its background', () => {
  for (const value of [-3, -1, -0.3, 0, 0.3, 1, 3]) {
    for (const ci of [0.05, 2]) {
      const colors = cellColors(value, ci, 1, TOKENS);
      assert.ok(
        contrast(colors.bg, colors.fg) >= 4.5,
        `${value} ±${ci}: ${colors.bg} on ${colors.fg}`,
      );
    }
  }
});

test('one extreme bot cannot squash the score plot', () => {
  const field = Array.from({ length: 19 }, (_, i) => ({ score: 0.1 * (i - 9) / 3, ci95: 0.15 }));
  field.push({ score: 12, ci95: 1 }); // an always-shove against a folder

  const max = scoreAxisMax(field);

  assert.ok(max <= 1, `axis limit ${max} should follow the typical teams`);
  assert.equal(isClipped(12, max), true);
  assert.equal(isClipped(0.2, max), false);
  assert.equal(isClipped(null, max), false);
});

test('axis limits fit every interval and one outlier cannot wash out a matrix', () => {
  const teams = [
    { score: 0.4, ci95: 0.2 },
    { score: -0.9, ci95: 0.3 },
    { score: null, ci95: null },
  ];
  assert.equal(scoreAxisMax(teams), 2); // 1.2 rounds up to 2
  assert.equal(scoreAxisMax([]), 0.1);

  const values = [...Array(20).fill(0.3), 40];
  assert.ok(matrixMax(values) < 1, 'the shover outlier is clipped, not scaled to');
  assert.equal(matrixMax([]), 0.25);
});
