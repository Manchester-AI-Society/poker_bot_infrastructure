// Replay frames must agree with the engine's own results on real hands.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  buildFrames,
  checkFrames,
  parseCard,
  swingFor,
} from '../../arena/site/js/replay-core.js';

const fixture = JSON.parse(
  readFileSync(new URL('./fixtures/hands.json', import.meta.url), 'utf8'),
);

test('fixture is real, varied play', () => {
  const ends = new Set(fixture.hands.map((h) => h.end));
  assert.ok(fixture.hands.length >= 100);
  assert.ok(ends.has('fold') && ends.has('showdown'));
  const split = fixture.hands.filter((h) => h.res.every(([won]) => won > 0));
  assert.ok(split.length > 0, 'fixture should contain split pots');
});

test('every real hand replays with chips conserved and the engine result', () => {
  for (const hand of fixture.hands) {
    const frames = buildFrames(hand, { reveal: fixture.reveal });
    const problems = checkFrames(hand, frames);
    assert.deepEqual(problems, [], `hand ${hand.n}: ${problems.join('; ')}`);
  }
});

test('a hand always starts with blinds and ends with one result frame', () => {
  for (const hand of fixture.hands) {
    const frames = buildFrames(hand, {});
    assert.equal(frames[0].kind, 'start');
    assert.equal(frames[1].kind, 'blind');
    assert.equal(frames[2].kind, 'blind');
    assert.equal(frames.filter((f) => f.kind === 'end').length, 1);
    assert.equal(frames[frames.length - 1].kind, 'end');
  }
});

test('the board is revealed street by street and never shrinks', () => {
  for (const hand of fixture.hands) {
    const frames = buildFrames(hand, {});
    let seen = 0;
    for (const frame of frames) {
      assert.ok(frame.board >= seen, 'board went backwards');
      seen = frame.board;
    }
    assert.equal(seen, hand.board.length, 'all dealt cards get shown');
  }
});

test('an all-in call deals out the remaining board before showdown', () => {
  const hand = fixture.hands.find(
    (h) =>
      h.end === 'showdown' &&
      h.board.length === 5 &&
      h.actions.every(([, , , street]) => street === 'preflop'),
  );
  assert.ok(hand, 'fixture should include a preflop all-in showdown');

  const frames = buildFrames(hand, {});
  const streets = frames.filter((f) => f.kind === 'street').map((f) => f.street);

  assert.deepEqual(streets, ['flop', 'turn', 'river']);
});

test('raise_to is a total for the street, calls and bets are chips added', () => {
  const hand = {
    seats: ['a', 'b'],
    stacks: [2000, 2000],
    sb: 10,
    bb: 20,
    dealer: 0,
    hole: null,
    board: [],
    actions: [
      [0, 'post_small_blind', 10, 'preflop', 0],
      [1, 'post_big_blind', 20, 'preflop', 0],
      [0, 'raise_to', 60, 'preflop', 0], // 10 already in -> adds 50
      [1, 'raise_to', 180, 'preflop', 0], // 20 already in -> adds 160
      [0, 'fold', null, 'preflop', 0],
    ],
    end: 'fold',
    // The engine counts the uncalled 120 handed back as part of B's winnings.
    res: [
      [0, 'Folded'],
      [240, 'Won by Fold'],
    ],
    net: [-60, 60],
  };

  const frames = buildFrames(hand, {});
  const afterRaise = frames[3];
  const afterReraise = frames[4];

  assert.equal(afterRaise.seats[0].stack, 1940);
  assert.equal(afterRaise.seats[0].bet, 60);
  assert.equal(afterReraise.seats[1].stack, 1820);
  assert.equal(afterReraise.pot, 60 + 180);
  assert.match(afterReraise.text, /b raises to 180/);
  // The final stacks come from the engine, including the uncalled 120.
  assert.deepEqual(checkFrames(hand, frames), []);
  assert.equal(frames.at(-1).seats[1].stack, 2060);
});

test('hole cards are face down until the end unless every card is public', () => {
  const hand = fixture.hands.find((h) => h.end === 'showdown');

  const hidden = buildFrames(hand, { reveal: 'showdown' });
  assert.ok(hidden.slice(0, -1).every((f) => f.faceUp === false));
  assert.equal(hidden.at(-1).faceUp, true);

  const open = buildFrames(hand, { reveal: 'all' });
  assert.ok(open.every((f) => f.faceUp === true));
});

test('with no hole cards published nothing is ever shown face up', () => {
  const hand = { ...fixture.hands[0], hole: null };

  const frames = buildFrames(hand, { reveal: 'showdown' });

  assert.ok(frames.every((f) => f.faceUp === false));
});

test('faults are flagged on the move that fell back to a default', () => {
  const hand = structuredClone(fixture.hands.find((h) => h.actions.length > 4));
  hand.actions[3][4] = 1;

  const frames = buildFrames(hand, {});

  assert.equal(frames[4].fault, true);
  assert.equal(frames.filter((f) => f.fault).length, 1);
});

test('cards parse for display', () => {
  assert.deepEqual(parseCard('TD'), {
    rank: '10',
    suit: 'd',
    glyph: '♦',
    red: true,
    text: '10♦',
  });
  assert.equal(parseCard('AS').red, false);
  assert.equal(parseCard('2H').text, '2♥');
});

test('swing is read from the named bot side', () => {
  const hand = { seats: ['a', 'b'], net: [-40, 40] };
  assert.equal(swingFor(hand, 'a'), -40);
  assert.equal(swingFor(hand, 'b'), 40);
  assert.equal(swingFor(hand, 'zzz'), 0);
});
