import test from 'node:test';
import assert from 'node:assert/strict';
import { SIZES, chooseLayout, collides, maxRingWidth, ringPositions } from '../../arena/site/js/table-layout-core.js';

const WIDTHS = [320, 326, 360, 390, 430, 520, 640, 768, 900, 1216, 1920];

test('every ring layout keeps the seats inside the box, apart, and off the middle', () => {
  for (const width of WIDTHS) {
    for (let n = 1; n <= 23; n += 1) {
      for (const scale of [1, 1.5]) {
        const layout = chooseLayout(n, width, scale);
        if (layout.mode === 'list') continue;
        assert.equal(layout.positions.length, n);
        assert.ok(layout.W <= width && layout.W <= maxRingWidth(n) * scale);
        const { w, h } = layout.size;
        assert.equal(collides(layout.positions, layout.W, layout.H, w, h, { w: 0, h: 0 }), false, `n=${n} W=${width} s=${scale}`);
        const middle = scale * (layout.W < 520 * scale ? 176 : 214);
        assert.equal(collides(layout.positions, layout.W, layout.H, w, h, { w: middle, h: 118 * scale }), false, `n=${n} W=${width}`);
      }
    }
  }
});

test('on a desktop screen every size from 2 to 23 players is a ring', () => {
  for (const width of [900, 1216, 1920]) {
    for (let n = 2; n <= 23; n += 1) assert.equal(chooseLayout(n, width).mode, 'ring', `n=${n} W=${width}`);
  }
});

test('on a phone heads-up is a ring and a crowd is a list', () => {
  // A 390 px phone leaves about 326 px inside the page padding.
  for (const width of [326, 360, 390, 430]) {
    for (const n of [2]) assert.equal(chooseLayout(n, width).mode, 'ring', `n=${n} W=${width}`);
    for (const n of [10, 15, 23]) assert.equal(chooseLayout(n, width).mode, 'list', `n=${n} W=${width}`);
    // Seats that fit on a phone are never the tiniest size.
    for (let n = 2; n <= 23; n += 1) {
      const layout = chooseLayout(n, width);
      if (layout.mode === 'ring') assert.notEqual(layout.size.name, 'xs');
    }
  }
});

test('more players get smaller seats, and the first seat is at the bottom', () => {
  const order = SIZES.map((s) => s.name);
  const at = (n) => order.indexOf(chooseLayout(n, 1216).size.name);
  assert.equal(at(2), 0);
  assert.ok(at(6) <= at(12) && at(12) <= at(23));
  assert.ok(at(23) > at(6));
  const { positions, W } = chooseLayout(6, 900);
  assert.ok(Math.abs(positions[0].x - W / 2) < 1e-6);
  assert.ok(positions[0].y > positions[3].y); // seat 0 is below its opposite seat
});

test('ring positions go clockwise from the bottom and stay on the ellipse', () => {
  const p = ringPositions(4, 800, 400, 100, 60);
  assert.ok(Math.abs(p[0].x - 400) < 1e-6 && p[0].y > 300); // bottom
  assert.ok(p[1].x < 100); // then the left
  assert.ok(Math.abs(p[2].x - 400) < 1e-6 && p[2].y < 100); // top
  assert.ok(p[3].x > 700); // then the right
});
