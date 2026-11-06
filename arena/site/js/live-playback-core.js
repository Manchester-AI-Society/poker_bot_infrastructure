// The live table's playback engine. Pure (no DOM, no timers of its own), so
// Node can test it against the real exported hands (tests/site_js).
//
// The exporter publishes finished hands in coarse batches, with the real time
// each step took (bots answer in milliseconds). Two jobs here:
//
//   1. buildHandFrames: one hand -> a list of full snapshots ("frames"), each
//      with how long a person should look at it. Every number in a frame comes
//      from the data (the stacks before the blinds, the blinds, and each
//      step's own pot / stack / bet), so chips are conserved in every frame:
//      the stacks plus the pot always add up to the same total, and the last
//      frame's stacks are exactly `showdown.stacks`.
//      Hole cards appear only in the showdown frames, and only for the players
//      in `showdown.hole_cards`; nothing else is ever put in a frame.
//
//   2. Playback: walks the frames of the hands it was fed at a human pace,
//      independent of the real `dt`. When it runs out of hands it waits at the
//      live edge until more are fed. If too many hands are queued it speeds up
//      smoothly so the page stays near the live edge.
//
// Time is passed in (tick(dtMs)), never read, so the tests are deterministic.

import { parseCard } from './replay-core.js';

/** How long each kind of frame is held at 1x, in milliseconds. */
export const HOLD = {
  deal: 1500,
  action: 1200,
  street: 2000,
  showdown: 2200,
  endShowdown: 1800, // with the showdown frame: about 4 s at a showdown
  endFold: 2000,
};

export const STREET_LABEL = { preflop: 'Pre-flop', flop: 'Flop', turn: 'Turn', river: 'River', showdown: 'Showdown' };

const STREET_AT = { 3: 'flop', 4: 'turn', 5: 'river' };
const CARD = /^(?:[2-9]|10|[TJQKA])[SHDC]$/i;

/** Hands behind the live edge a new viewer starts at. */
export const LEAD_HANDS = 2;
/** Up to this many unseen hands play at normal speed. */
export const FREE_QUEUE = 3;
export const MAX_CATCH_UP = 8;
/** From this catch-up factor the single actions are skipped (streets and results stay). */
export const SKIP_ACTIONS_AT = 6;
export const MIN_HOLD_MS = 60;
export const SPEEDS = [1, 2, 4];

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const cardList = (cards) => (Array.isArray(cards) ? cards.filter((c) => typeof c === 'string' && CARD.test(c)) : []);

export function cardsText(cards) {
  return cardList(cards)
    .map((c) => parseCard(c).text)
    .join(' ');
}

function actionText(name, step, stackAfter, betAfter) {
  const bet = finite(betAfter) ? betAfter : step.amount;
  let text;
  switch (step.action) {
    case 'fold':
      text = `${name} folds`;
      break;
    case 'check':
      text = `${name} checks`;
      break;
    case 'call':
      text = `${name} calls ${step.amount}`;
      break;
    case 'bet':
      text = `${name} bets ${bet}`;
      break;
    case 'raise_to':
      text = `${name} raises to ${bet}`;
      break;
    default:
      text = `${name} ${String(step.action)}${finite(step.amount) ? ` ${step.amount}` : ''}`;
  }
  if (step.action !== 'fold' && stackAfter === 0) text += ' (all in)';
  if (step.timeout) text += ' (timed out)';
  return text;
}

/** What goes beside a seat after its action: the same words without the name. */
function noteFrom(text, name) {
  return text.startsWith(`${name} `) ? text.slice(name.length + 1) : text;
}

/**
 * The frames of one hand, in order. Each is a full snapshot:
 *   {kind: 'deal'|'action'|'street'|'showdown'|'end', hold, text, n, index,
 *    dealer, street, board, pot, potWon, level, actor, next,
 *    seats: [{name, stack, bet, state: 'in'|'folded'|'allin'|'out',
 *             note, blind, hole, hand, winnings, winner, dealer}]}
 * Seats are in the hand's seat order. `hole` is null except in the showdown
 * and end frames for the players whose cards the data reveals.
 */
export function buildHandFrames(hand) {
  const names = Array.isArray(hand.players) ? hand.players.map(String) : [];
  const count = names.length;
  const index = new Map(names.map((name, i) => [name, i]));
  const before = hand.stacks || {};
  const stacks = names.map((name) => (finite(before[name]) ? before[name] : 0));
  const sitting = stacks.map((chips) => chips > 0);
  const bets = new Array(count).fill(0);
  const folded = new Array(count).fill(false);
  const notes = new Array(count).fill('');
  const blinds = new Array(count).fill('');
  const posted = Array.isArray(hand.blinds) ? hand.blinds : [];
  let pot = 0;
  // The data lists the blinds in seat order, so the big blind can come first:
  // the bigger amount is the big blind (a tie: the later one).
  const bigFirst = posted.length === 2 && posted[0].amount > posted[1].amount;
  for (const [order, blind] of posted.entries()) {
    const i = index.get(String(blind.player_id));
    if (i === undefined || !finite(blind.amount)) continue;
    stacks[i] -= blind.amount;
    bets[i] += blind.amount;
    pot += blind.amount;
    sitting[i] = true;
    blinds[i] = posted.length === 2 ? (order === (bigFirst ? 0 : 1) ? 'BB' : 'SB') : 'blind';
  }
  const dealer = Number.isInteger(hand.dealer) && hand.dealer >= 0 && hand.dealer < count ? hand.dealer : null;
  const level = hand.level && finite(hand.level.small) && finite(hand.level.big) ? { small: hand.level.small, big: hand.level.big } : null;
  const steps = Array.isArray(hand.steps) ? hand.steps : [];
  const showdown = hand.showdown || null;

  let board = [];
  let street = 'preflop';
  let potWon = 0;
  const holes = new Array(count).fill(null);
  const handNames = new Array(count).fill('');
  const winnings = new Array(count).fill(0);
  let over = false;
  const frames = [];

  const stateOf = (i) => {
    if (!sitting[i]) return 'out';
    if (over && stacks[i] === 0) return 'out';
    if (folded[i]) return 'folded';
    if (stacks[i] === 0) return 'allin';
    return 'in';
  };

  const nextActor = (after) => {
    for (let k = after + 1; k < steps.length; k += 1) {
      if (steps[k].type === 'action' && index.has(String(steps[k].player))) return index.get(String(steps[k].player));
    }
    return null;
  };

  const snap = (kind, text, hold, actor, next) => {
    frames.push({
      kind,
      hold,
      text,
      n: hand.n,
      index: frames.length,
      dealer,
      street,
      board: board.slice(),
      pot,
      potWon,
      level,
      actor,
      next,
      seats: names.map((name, i) => ({
        name,
        stack: stacks[i],
        bet: bets[i],
        state: stateOf(i),
        note: notes[i],
        blind: blinds[i],
        hole: holes[i],
        hand: handNames[i],
        winnings: winnings[i],
        winner: winnings[i] > 0,
        dealer: i === dealer,
      })),
    });
  };

  const newStreet = (name, cards) => {
    street = name;
    board = cards.slice();
    bets.fill(0);
    notes.fill('');
  };

  const blindText = level ? ` · blinds ${level.small}/${level.big}` : '';
  snap('deal', `Hand ${hand.n}${blindText}`, HOLD.deal, null, nextActor(-1));

  steps.forEach((step, k) => {
    if (step.type === 'street') {
      const cards = cardList(step.board);
      newStreet(String(step.street), cards);
      snap('street', `${STREET_LABEL[step.street] || step.street}: ${cardsText(cards)}`, HOLD.street, null, nextActor(k));
      return;
    }
    if (step.type !== 'action') return;
    const i = index.get(String(step.player));
    if (i === undefined) return;
    const stack = finite(step.stack) ? step.stack : stacks[i];
    const bet = finite(step.bet) ? step.bet : bets[i];
    pot = finite(step.pot) ? step.pot : pot + (stacks[i] - stack);
    stacks[i] = stack;
    bets[i] = bet;
    if (step.action === 'fold') folded[i] = true;
    if (Object.hasOwn(STREET_LABEL, step.street)) street = step.street;
    const text = actionText(names[i], step, stack, bet);
    notes[i] = noteFrom(text, names[i]);
    snap('action', text, HOLD.action, i, nextActor(k));
  });

  if (!showdown) return frames;

  // An all-in hand can reach the showdown with cards the steps never dealt:
  // deal them one street at a time, as the table would.
  const full = cardList(showdown.board);
  if (full.length > board.length && full.slice(0, board.length).every((card, i) => card === board[i])) {
    for (let size = board.length + 1; size <= full.length; size += 1) {
      if (!STREET_AT[size]) continue;
      const cards = full.slice(0, size);
      newStreet(STREET_AT[size], cards);
      snap('street', `${STREET_LABEL[STREET_AT[size]]}: ${cardsText(cards)}`, HOLD.street, null, null);
    }
  }

  const results = Array.isArray(showdown.results) ? showdown.results : [];
  const shown = showdown.hole_cards && typeof showdown.hole_cards === 'object' ? showdown.hole_cards : null;
  let revealed = false;
  if (shown) {
    for (const [name, cards] of Object.entries(shown)) {
      const i = index.get(name);
      const pair = cardList(cards);
      if (i !== undefined && pair.length) {
        holes[i] = pair;
        revealed = true;
      }
    }
  }
  if (revealed) {
    for (const result of results) {
      const i = index.get(String(result.player_id));
      if (i !== undefined && holes[i] && typeof result.hand === 'string') handNames[i] = result.hand;
    }
    notes.fill('');
    for (const [i, name] of names.entries()) if (holes[i] && handNames[i]) notes[i] = handNames[i];
    street = 'showdown';
    snap('showdown', 'Showdown', HOLD.showdown, null, null);
  }

  // The payout. The data's own final stacks win; without them, add the winnings.
  const paid = names.map((name) => {
    const r = results.find((x) => String(x.player_id) === name);
    return r && finite(r.winnings) ? r.winnings : 0;
  });
  const total = pot;
  over = true;
  names.forEach((name, i) => {
    const after = showdown.stacks && finite(showdown.stacks[name]) ? showdown.stacks[name] : stacks[i] + paid[i];
    stacks[i] = after;
    winnings[i] = paid[i];
  });
  pot = 0;
  potWon = total;
  bets.fill(0);
  notes.fill('');
  const winners = names.map((name, i) => ({ name, i, won: paid[i] })).filter((w) => w.won > 0);
  for (const w of winners) notes[w.i] = `wins ${w.won}`;
  for (let i = 0; i < count; i += 1) {
    if (sitting[i] && stacks[i] === 0 && !notes[i]) notes[i] = 'eliminated';
  }
  const parts = winners.map((w) => {
    const label = handNames[w.i];
    const how = revealed && label && label !== 'Won by Fold' ? ` with ${label}` : '';
    return `${w.name} wins ${w.won}${how}`;
  });
  let text = parts.length ? parts.join('; ') : 'Hand over';
  if (!revealed && winners.length === 1) text += ' (everyone else folded)';
  const out = names.filter((name, i) => sitting[i] && stacks[i] === 0 && !winners.some((w) => w.i === i));
  if (out.length) text += `. Eliminated: ${out.join(', ')}`;
  snap('end', text, revealed ? HOLD.endShowdown : HOLD.endFold, null, null);
  return frames;
}

/** Chips on the table in a frame: every stack plus the pot. */
export function chipTotal(frame) {
  return frame.seats.reduce((sum, seat) => sum + seat.stack, 0) + frame.pot;
}

/** How many times faster than normal to play when `unseen` hands are queued. */
export function catchUpFactor(unseen) {
  if (!(unseen > FREE_QUEUE)) return 1;
  return Math.min(MAX_CATCH_UP, 1 + (unseen - FREE_QUEUE) * 0.5);
}

/**
 * Walks the hands of one table at a human pace. Feed it the table file's
 * `hands`; call tick(dtMs) as time passes; read frame() to draw.
 *
 * It never advances past the data: at the last frame of the last hand it
 * waits ('waiting'), holding the time already spent, and carries on at the
 * next tick after more hands are fed.
 */
export class Playback {
  constructor({ lead = LEAD_HANDS, progress = null } = {}) {
    this.lead = lead;
    this.hands = [];
    this.cache = new Map();
    this.cursor = progress && Number.isInteger(progress.n) ? { n: progress.n, f: Math.max(0, progress.f | 0) } : null;
    this.paused = false;
    this.speed = 1;
    this.elapsed = 0;
    this.version = null;
    this.finished = false; // the table's own status, set by feed()
  }

  /**
   * Gives it the hands now visible (the table file's list). A feed with the
   * same `version` as the last one is ignored. Returns how many hands are new.
   */
  feed(hands, { version = null, finished = false } = {}) {
    if (version != null && version === this.version) return 0;
    this.version = version;
    this.finished = Boolean(finished);
    const list = (Array.isArray(hands) ? hands : []).filter((h) => h && Number.isInteger(h.n)).sort((a, b) => a.n - b.n);
    const known = new Set(this.hands.map((h) => h.n));
    const added = list.filter((h) => !known.has(h.n)).length;
    this.hands = list;
    for (const key of [...this.cache.keys()]) if (!list.some((h) => h.n === key)) this.cache.delete(key);
    if (!list.length) {
      this.cursor = null;
      return added;
    }
    const at = this.cursor && list.findIndex((h) => h.n === this.cursor.n);
    if (this.cursor && at >= 0) {
      const frames = this.framesOf(at);
      this.cursor.f = Math.min(this.cursor.f, frames.length - 1);
    } else if (this.cursor && this.cursor.n < list[0].n) {
      // The hand being watched has rolled off the file: carry on from the oldest.
      this.cursor = { n: list[0].n, f: 0 };
      this.elapsed = 0;
    } else {
      this.cursor = { n: list[Math.max(0, list.length - 1 - this.lead)].n, f: 0 };
      this.elapsed = 0;
    }
    return added;
  }

  framesOf(handIndex) {
    const hand = this.hands[handIndex];
    if (!this.cache.has(hand.n)) this.cache.set(hand.n, buildHandFrames(hand));
    return this.cache.get(hand.n);
  }

  handIndex() {
    if (!this.cursor) return -1;
    return this.hands.findIndex((h) => h.n === this.cursor.n);
  }

  /** The frame on screen, or null before there is any hand. */
  frame() {
    const at = this.handIndex();
    if (at < 0) return null;
    return this.framesOf(at)[this.cursor.f];
  }

  /** Frames of the current hand up to and including the one on screen. */
  shownFrames() {
    const at = this.handIndex();
    return at < 0 ? [] : this.framesOf(at).slice(0, this.cursor.f + 1);
  }

  /** The action log of the current hand so far: one line per frame after the deal. */
  log() {
    return this.shownFrames()
      .slice(1)
      .map((f) => ({ text: f.text, kind: f.kind }));
  }

  /** Hands after the one being watched. */
  unseen() {
    const at = this.handIndex();
    return at < 0 ? 0 : this.hands.length - 1 - at;
  }

  catchUp() {
    return catchUpFactor(this.unseen());
  }

  atEdge() {
    const at = this.handIndex();
    return at >= 0 && at === this.hands.length - 1 && this.cursor.f >= this.framesOf(at).length - 1;
  }

  /** 'empty' | 'paused' | 'waiting' | 'finished' | 'playing' */
  state() {
    if (!this.cursor) return 'empty';
    if (this.atEdge()) return this.finished ? 'finished' : 'waiting';
    return this.paused ? 'paused' : 'playing';
  }

  /** How long the frame on screen is held now, given speed and catch-up. */
  holdMs() {
    const frame = this.frame();
    if (!frame) return 0;
    return Math.max(MIN_HOLD_MS, frame.hold / (this.speed * this.catchUp()));
  }

  /** Moves to the next frame; false when there is none (the live edge). */
  advance() {
    const at = this.handIndex();
    if (at < 0) return false;
    const skip = this.catchUp() >= SKIP_ACTIONS_AT;
    const frames = this.framesOf(at);
    if (this.cursor.f < frames.length - 1) {
      this.cursor.f += 1;
      // Far behind: leave out the single actions of this hand, keep the rest.
      while (skip && frames[this.cursor.f].kind === 'action' && this.cursor.f < frames.length - 1) this.cursor.f += 1;
    } else if (at < this.hands.length - 1) {
      this.cursor = { n: this.hands[at + 1].n, f: 0 };
    } else {
      return false;
    }
    return true;
  }

  /**
   * Lets `dtMs` of time pass. Returns how many frames it moved. A paused
   * playback does not move. At the live edge the time already spent is kept,
   * so new hands start playing at the next tick.
   */
  tick(dtMs) {
    if (this.paused || !this.cursor || !(dtMs > 0)) return 0;
    let moved = 0;
    this.elapsed += dtMs;
    for (;;) {
      const hold = this.holdMs();
      if (this.elapsed < hold) break;
      if (!this.advance()) {
        this.elapsed = hold; // waiting: ready to move on as soon as there is more
        break;
      }
      this.elapsed -= hold;
      moved += 1;
    }
    return moved;
  }

  /** Skips the backlog: the start of the newest hand. */
  jumpToLive() {
    if (!this.hands.length) return;
    this.cursor = { n: this.hands[this.hands.length - 1].n, f: 0 };
    this.elapsed = 0;
  }

  setSpeed(speed) {
    if (SPEEDS.includes(speed)) this.speed = speed;
  }

  pause() {
    this.paused = true;
  }

  resume() {
    this.paused = false;
  }

  togglePause() {
    this.paused = !this.paused;
  }

  /** What to keep to carry on later (see the constructor's `progress`). */
  progress() {
    return this.cursor ? { n: this.cursor.n, f: this.cursor.f } : null;
  }

  /** Where in the hands the viewer is, as {n, hands, behind}: for the status line. */
  position() {
    const at = this.handIndex();
    return { n: at < 0 ? null : this.hands[at].n, hands: this.hands.length, behind: this.unseen() };
  }
}

/** The Playback kept for each table, so a redraw of the page carries on where it was. */
const registry = new Map();

export function playbackFor(matchId) {
  if (!registry.has(matchId)) registry.set(matchId, new Playback());
  return registry.get(matchId);
}

export function forgetPlaybacks() {
  registry.clear();
}
