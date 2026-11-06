import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  FREE_QUEUE,
  HOLD,
  LEAD_HANDS,
  MAX_CATCH_UP,
  Playback,
  buildHandFrames,
  catchUpFactor,
  chipTotal,
  forgetPlaybacks,
  playbackFor,
} from '../../arena/site/js/live-playback-core.js';

const load = (name) => JSON.parse(readFileSync(new URL(`./fixtures/live/${name}.json`, import.meta.url), 'utf8'));
const TABLES = {
  'heads-up': load('heads-up'),
  'final-3-handed': load('final-3-handed'),
  'ten-players': load('ten-players'),
  'twenty-three': load('twenty-three'),
};
const allHands = () => Object.entries(TABLES).flatMap(([name, t]) => t.hands.map((hand) => ({ name, hand })));

const stepsOf = (hand, type) => hand.steps.filter((s) => s.type === type);
const handsOf = (name, from = 0, to = undefined) => TABLES[name].hands.slice(from, to);

test('the samples are what the tests assume: all sizes, both endings, an all-in', () => {
  const sizes = new Set(Object.values(TABLES).map((t) => t.players.length));
  assert.deepEqual([...sizes].sort((a, b) => a - b), [2, 3, 10, 23]);
  const hands = allHands().map((x) => x.hand);
  assert.ok(hands.some((h) => h.showdown.hole_cards));
  assert.ok(hands.some((h) => !h.showdown.hole_cards));
  assert.ok(hands.some((h) => h.steps.some((s) => s.type === 'action' && s.stack === 0 && s.action !== 'fold')));
});

test('chips are conserved in every frame of every real hand, and the last frame matches showdown.stacks', () => {
  let frames = 0;
  for (const { name, hand } of allHands()) {
    const total = Object.values(hand.stacks).reduce((a, b) => a + b, 0);
    const list = buildHandFrames(hand);
    assert.ok(list.length >= 2, `${name} hand ${hand.n}`);
    for (const frame of list) {
      assert.equal(chipTotal(frame), total, `${name} hand ${hand.n} frame ${frame.index} (${frame.kind})`);
      frames += 1;
    }
    const last = list[list.length - 1];
    assert.equal(last.kind, 'end');
    assert.equal(last.pot, 0);
    assert.deepEqual(
      Object.fromEntries(last.seats.map((s) => [s.name, s.stack])),
      hand.showdown.stacks,
      `${name} hand ${hand.n}`,
    );
  }
  assert.ok(frames > 1000);
});

test('hole cards appear only at the showdown, only for the players the data names', () => {
  for (const { name, hand } of allHands()) {
    const shown = hand.showdown.hole_cards;
    const dataBoard = hand.showdown.board || [];
    const known = new Set([...dataBoard, ...stepsOf(hand, 'street').flatMap((s) => s.board)]);
    for (const frame of buildHandFrames(hand)) {
      for (const seat of frame.seats) {
        if (!seat.hole) continue;
        assert.ok(['showdown', 'end'].includes(frame.kind), `${name} hand ${hand.n}: ${frame.kind}`);
        assert.ok(shown && shown[seat.name], `${name} hand ${hand.n}: ${seat.name} was not revealed`);
        assert.deepEqual(seat.hole, shown[seat.name]);
      }
      // Never a card on the board that the data does not list.
      for (const card of frame.board) assert.ok(known.has(card), `${name} hand ${hand.n}`);
      if (!shown) assert.ok(frame.seats.every((s) => s.hole === null));
    }
  }
});

test('a hand won by a fold: deal, actions, end; no card is revealed', () => {
  const hand = TABLES['final-3-handed'].hands.find((h) => h.n === 8);
  assert.equal(hand.showdown.hole_cards, null);
  const frames = buildHandFrames(hand);
  assert.deepEqual(
    frames.map((f) => f.kind),
    ['deal', 'action', 'action', 'end'],
  );
  const end = frames[frames.length - 1];
  assert.equal(end.hold, HOLD.endFold);
  assert.match(end.text, /wins 60 \(everyone else folded\)/);
  assert.equal(end.seats.filter((s) => s.winner).length, 1);
  assert.equal(end.potWon, 60);
  assert.ok(frames.every((f) => f.seats.every((s) => s.hole === null)));
  assert.match(frames[1].text, /folds$/);
});

test('a showdown reveals the contenders at the showdown frame and keeps them to the end', () => {
  const hand = TABLES['final-3-handed'].hands.find((h) => h.n === 6);
  const names = Object.keys(hand.showdown.hole_cards);
  assert.equal(names.length, 2); // the third player folded
  const frames = buildHandFrames(hand);
  assert.deepEqual(
    frames.map((f) => f.kind).slice(-2),
    ['showdown', 'end'],
  );
  const reveal = frames[frames.length - 2];
  assert.deepEqual(
    reveal.seats.filter((s) => s.hole).map((s) => s.name).sort(),
    [...names].sort(),
  );
  assert.equal(reveal.pot > 0, true);
  assert.equal(reveal.hold, HOLD.showdown);
  assert.equal(reveal.board.length, 5);
  const folded = reveal.seats.filter((s) => s.state === 'folded');
  assert.equal(folded.length, 1);
  assert.equal(folded[0].hole, null);
  const end = frames[frames.length - 1];
  assert.equal(end.hold, HOLD.endShowdown);
  assert.equal(HOLD.showdown + HOLD.endShowdown, 4000); // about four seconds at a showdown
  assert.deepEqual(
    end.seats.filter((s) => s.hole).map((s) => s.name).sort(),
    [...names].sort(),
  );
  assert.ok(reveal.seats.filter((s) => s.hole).every((s) => s.hand));
});

test('before the showdown nobody is shown a card: the seats still in the hand hold face-down cards', () => {
  const hand = TABLES['final-3-handed'].hands[0];
  const frames = buildHandFrames(hand);
  for (const frame of frames.filter((f) => f.kind !== 'showdown' && f.kind !== 'end')) {
    assert.ok(frame.seats.every((s) => s.hole === null));
    assert.ok(frame.seats.filter((s) => s.state === 'in').length >= 2);
  }
});

test('the dealer button and the posted blinds sit where the data puts them (3 handed)', () => {
  for (const hand of TABLES['final-3-handed'].hands) {
    const first = buildHandFrames(hand)[0];
    assert.equal(first.kind, 'deal');
    assert.deepEqual(
      first.seats.map((s) => s.dealer),
      hand.players.map((_, i) => i === hand.dealer),
    );
    // The data lists the blinds in seat order: the bigger amount is the big blind.
    const [lo, hi] = [...hand.blinds].sort((a, b) => a.amount - b.amount);
    const small = first.seats.find((s) => s.blind === 'SB');
    const big = first.seats.find((s) => s.blind === 'BB');
    assert.equal(small.name, lo.player_id);
    assert.equal(big.name, hi.player_id);
    assert.equal(small.bet, lo.amount);
    assert.equal(big.bet, hi.amount);
    assert.equal(small.stack, hand.stacks[small.name] - small.bet);
    assert.equal(first.pot, lo.amount + hi.amount);
    assert.deepEqual(first.level, hand.level);
    // The first to act is the player the first step names, and it is shown as next.
    assert.equal(first.seats[first.next].name, stepsOf(hand, 'action')[0].player);
  }
});

test('heads up: both players post a blind and the first actor is the next to act', () => {
  const hand = TABLES['heads-up'].hands[0];
  const first = buildHandFrames(hand)[0];
  assert.equal(first.seats.length, 2);
  assert.equal(first.seats.filter((s) => s.blind).length, 2);
  assert.equal(first.seats[first.next].name, stepsOf(hand, 'action')[0].player);
});

test('actions show the actor, the bet and who acts next; streets reset the bets', () => {
  const hand = TABLES['final-3-handed'].hands.find((h) => h.n === 1);
  const frames = buildHandFrames(hand);
  const call = frames[1];
  assert.equal(call.kind, 'action');
  assert.match(call.text, /calls 10$/);
  assert.equal(call.seats[call.actor].bet, 10);
  assert.equal(call.seats[call.actor].note, 'calls 10');
  assert.notEqual(call.next, null);
  const flop = frames.find((f) => f.kind === 'street');
  assert.equal(flop.street, 'flop');
  assert.equal(flop.board.length, 3);
  assert.ok(flop.seats.every((s) => s.bet === 0));
  assert.match(flop.text, /^Flop: /);
});

test('an all-in is called out, and a runout the steps never dealt is dealt street by street', () => {
  let allIn = 0;
  let runouts = 0;
  for (const { name, hand } of allHands()) {
    const dealt = stepsOf(hand, 'street');
    const lastBoard = dealt.length ? dealt[dealt.length - 1].board : [];
    const frames = buildHandFrames(hand);
    if (frames.some((f) => f.seats.some((s) => s.state === 'allin'))) {
      allIn += 1;
      const byAction = hand.steps.some((s) => s.type === 'action' && s.stack === 0 && s.action !== 'fold');
      if (byAction) assert.ok(frames.some((f) => /\(all in\)/.test(f.text)), `${name} ${hand.n}`);
    }
    if ((hand.showdown.board || []).length > lastBoard.length) {
      runouts += 1;
      const streets = frames.filter((f) => f.kind === 'street');
      assert.equal(streets[streets.length - 1].board.length, hand.showdown.board.length);
      // Boards only grow, a street at a time.
      let size = 0;
      for (const f of streets) {
        assert.ok(f.board.length > size);
        size = f.board.length;
      }
    }
  }
  assert.ok(allIn > 0);
  assert.ok(runouts > 0, 'the samples have no hand with an undealt runout');
});

test('a bust is shown as eliminated in the end frame', () => {
  const hand = TABLES['final-3-handed'].hands.find((h) => h.n === 20);
  const end = buildHandFrames(hand).pop();
  assert.equal(end.seats.filter((s) => s.state === 'out').length, 2);
  // One went out in this hand, the other had gone out before it.
  assert.match(end.text, /Eliminated: device-2-1793998903$/);
  assert.equal(end.seats.filter((s) => s.note === 'eliminated').length, 1);
  assert.ok(end.seats.filter((s) => s.state === 'out').every((s) => s.stack === 0));
  const winner = end.seats.find((s) => s.winner);
  assert.equal(winner.stack, 600);
});

test('a seat that started the hand with no chips is out and holds no cards', () => {
  const hand = TABLES['twenty-three'].hands.find((h) => Object.values(h.stacks).includes(0));
  assert.ok(hand, 'the 23 player sample has a busted seat');
  const zero = Object.entries(hand.stacks)
    .filter(([, v]) => v === 0)
    .map(([k]) => k);
  for (const frame of buildHandFrames(hand)) {
    for (const seat of frame.seats.filter((s) => zero.includes(s.name))) {
      assert.equal(seat.state, 'out');
      assert.equal(seat.hole, null);
    }
  }
});

test('a timeout is said in words and a hostile name stays plain text', () => {
  const hand = {
    n: 1,
    players: ['<b>x</b>', 'y'],
    dealer: 0,
    stacks: { '<b>x</b>': 100, y: 100 },
    blinds: [
      { player_id: '<b>x</b>', amount: 5 },
      { player_id: 'y', amount: 10 },
    ],
    level: { small: 5, big: 10 },
    eliminated: [],
    steps: [{ type: 'action', player: '<b>x</b>', action: 'fold', amount: null, street: 'preflop', pot: 15, stack: 95, bet: 5, timeout: true }],
    showdown: { results: [{ player_id: 'y', hand: 'Won by Fold', winnings: 15 }], stacks: { '<b>x</b>': 95, y: 105 }, hole_cards: null, board: null },
  };
  const frames = buildHandFrames(hand);
  assert.equal(frames[1].text, '<b>x</b> folds (timed out)');
  assert.equal(frames[1].seats[0].state, 'folded');
  assert.equal(chipTotal(frames[1]), 200);
  assert.equal(frames[2].text, 'y wins 15 (everyone else folded)');
});

test('a hand with garbage in it still yields frames and never throws', () => {
  const frames = buildHandFrames({
    n: 3,
    players: ['a', 'b'],
    stacks: {},
    blinds: [{ player_id: 'ghost', amount: 'x' }],
    steps: [{ type: 'action', player: 'nobody' }, { type: 'street', street: 'flop', board: ['??', 'AS'] }, { type: 'wat' }],
    showdown: { results: null, stacks: null, hole_cards: { a: ['no', 'AS'], zed: ['AH', 'AD'] }, board: 'x' },
  });
  assert.ok(frames.length >= 2);
  const shown = frames.flatMap((f) => f.seats.map((s) => s.hole)).filter(Boolean);
  assert.ok(shown.every((pair) => pair.length === 1 && pair[0] === 'AS'));
  assert.deepEqual(frames[1].board, ['AS']); // the invalid card is dropped
});

// ---- pacing ------------------------------------------------------------------

test('catch-up: normal speed for a short queue, then smoothly faster, then capped', () => {
  for (let n = 0; n <= FREE_QUEUE; n += 1) assert.equal(catchUpFactor(n), 1);
  let previous = 1;
  for (let n = FREE_QUEUE + 1; n < 40; n += 1) {
    const factor = catchUpFactor(n);
    assert.ok(factor >= previous, `${n}`);
    assert.ok(factor - previous <= 0.5 + 1e-9, 'no sudden jumps');
    assert.ok(factor <= MAX_CATCH_UP);
    previous = factor;
  }
  assert.equal(catchUpFactor(1000), MAX_CATCH_UP);
});

test('a new viewer starts a couple of hands before the live edge, not at hand 1', () => {
  const pb = new Playback();
  assert.equal(pb.state(), 'empty');
  assert.equal(pb.frame(), null);
  const hands = handsOf('ten-players');
  pb.feed(hands, { version: 'a' });
  assert.equal(pb.frame().n, hands[hands.length - 1 - LEAD_HANDS].n);
  assert.equal(pb.frame().kind, 'deal');
  assert.equal(pb.unseen(), LEAD_HANDS);
  // A table with fewer hands than the lead starts at its first hand.
  const few = new Playback();
  few.feed(handsOf('ten-players', 0, 2));
  assert.equal(few.frame().n, 1);
});

test('time moves the frames at a human pace, whatever the real dt was', () => {
  const pb = new Playback();
  pb.feed(handsOf('final-3-handed', 0, 4)); // hands 1..4; starts at hand 2
  assert.equal(pb.frame().n, 2);
  assert.equal(pb.tick(HOLD.deal - 1), 0);
  assert.equal(pb.frame().index, 0);
  assert.equal(pb.tick(1), 1);
  assert.equal(pb.frame().index, 1);
  // 100 ms ticks: each frame is held for about its own hold, no more, no less.
  let last = pb.frame();
  let heldSince = 0;
  let changes = 0;
  const holds = [];
  for (let elapsed = 0; pb.state() === 'playing' && elapsed < 60000; elapsed += 100) {
    pb.tick(100);
    heldSince += 100;
    if (pb.frame() !== last) {
      holds.push([last.hold, heldSince]);
      heldSince = 0;
      last = pb.frame();
      changes += 1;
    }
  }
  assert.ok(changes > 5);
  for (const [hold, took] of holds.slice(1)) assert.ok(Math.abs(took - hold) <= 100, `${took} vs ${hold}`);
});

test('it waits at the live edge, never advances past the data, and resumes when hands are fed', () => {
  const pb = new Playback();
  const hands = handsOf('final-3-handed');
  pb.feed(hands.slice(0, 5), { version: 'v1' });
  for (let i = 0; i < 2000 && pb.state() !== 'waiting'; i += 1) pb.tick(500);
  assert.equal(pb.state(), 'waiting');
  const edge = pb.progress();
  assert.equal(edge.n, 5);
  assert.equal(pb.frame().kind, 'end');
  // However long it waits, it stays put.
  for (let i = 0; i < 50; i += 1) assert.equal(pb.tick(60000), 0);
  assert.deepEqual(pb.progress(), edge);
  assert.equal(pb.advance(), false);
  // More hands arrive: it carries on from the next hand without replaying anything.
  assert.equal(pb.feed(hands.slice(0, 8), { version: 'v2' }), 3);
  assert.deepEqual(pb.progress(), edge);
  assert.equal(pb.tick(100), 1);
  assert.equal(pb.progress().n, 6);
  assert.equal(pb.progress().f, 0);
  assert.notEqual(pb.state(), 'waiting');
});

test('the same version fed twice is ignored, and a finished table says so at its end', () => {
  const pb = new Playback();
  const hands = handsOf('heads-up');
  pb.feed(hands, { version: 'x', finished: true });
  assert.equal(pb.feed(hands.slice(0, 1), { version: 'x' }), 0);
  assert.equal(pb.hands.length, hands.length);
  pb.jumpToLive();
  for (let i = 0; i < 200 && !pb.atEdge(); i += 1) pb.tick(1000);
  assert.equal(pb.state(), 'finished');
});

test('progress survives a refresh: the same player carries on, and a restored one does too', () => {
  const hands = handsOf('ten-players');
  const pb = new Playback();
  pb.feed(hands.slice(0, 9), { version: '1' });
  for (let i = 0; i < 30; i += 1) pb.tick(1000);
  const where = pb.progress();
  assert.ok(where.n > 6 || where.f > 0);
  // A refresh brings the same hands plus new ones: the cursor does not move.
  pb.feed(hands, { version: '2' });
  assert.deepEqual(pb.progress(), where);
  // A new object restored from the saved progress is in the same place.
  const again = new Playback({ progress: where });
  again.feed(hands, { version: '2' });
  assert.deepEqual(again.progress(), where);
  assert.equal(again.frame().text, pb.frame().text);
  // The page keeps one Playback per table across redraws.
  forgetPlaybacks();
  assert.equal(playbackFor('t1'), playbackFor('t1'));
  assert.notEqual(playbackFor('t1'), playbackFor('t2'));
});

test('when the hand being watched has rolled off the file, it carries on from the oldest', () => {
  const hands = handsOf('ten-players');
  const pb = new Playback({ progress: { n: 1, f: 5 } });
  pb.feed(hands.slice(4), { version: 'r' });
  assert.deepEqual(pb.progress(), { n: 5, f: 0 });
});

test('falling far behind speeds playback up, and jump to live skips the backlog', () => {
  const hands = handsOf('ten-players'); // 14 hands
  const slow = new Playback({ lead: 0 });
  slow.feed(hands.slice(0, 2), { version: 'a' });
  const normal = slow.holdMs();
  const behind = new Playback({ lead: 100 });
  behind.feed(hands, { version: 'a' });
  assert.equal(behind.frame().n, 1);
  assert.ok(behind.unseen() >= 12);
  assert.ok(behind.holdMs() < normal / 4, `${behind.holdMs()} vs ${normal}`);
  assert.ok(behind.catchUp() >= 6);
  // At that speed the single actions are left out of a hand.
  let moves = 0;
  while (behind.frame().n === 1 && behind.advance()) moves += 1;
  assert.ok(moves < buildHandFrames(hands[0]).length, 'actions were skipped');
  behind.jumpToLive();
  assert.equal(behind.frame().n, 14);
  assert.equal(behind.frame().index, 0);
  assert.equal(behind.unseen(), 0);
});

test('speed and pause: 4x is four times quicker, a paused playback does not move, resume carries on', () => {
  const hands = handsOf('final-3-handed', 0, 6);
  const a = new Playback();
  const b = new Playback();
  a.feed(hands);
  b.feed(hands);
  b.setSpeed(4);
  b.setSpeed(3); // not a choice: ignored
  assert.equal(b.speed, 4);
  assert.equal(a.holdMs(), b.holdMs() * 4);
  a.pause();
  assert.equal(a.state(), 'paused');
  const where = a.progress();
  assert.equal(a.tick(100000), 0);
  assert.deepEqual(a.progress(), where);
  a.resume();
  assert.ok(a.tick(100000) > 0);
  a.togglePause();
  assert.equal(a.paused, true);
});

test('the log of the hand is its frames so far, and ends with the result', () => {
  const pb = new Playback({ lead: 0 });
  pb.feed(handsOf('final-3-handed', 3, 4)); // hand 4: a fold win
  assert.deepEqual(pb.log(), []);
  while (pb.advance());
  const log = pb.log();
  assert.equal(log.length, buildHandFrames(handsOf('final-3-handed', 3, 4)[0]).length - 1);
  assert.match(log[log.length - 1].text, /wins/);
});
