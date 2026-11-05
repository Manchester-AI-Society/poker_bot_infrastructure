// Turns one stored hand into a list of frames a replayer can step through.
// Pure (no DOM), so Node tests can check it against real hand histories.
//
// A hand from the export looks like (see arena/export.py, public_hand):
//   seats, stacks, sb, bb, dealer, hole (or null), board (cards dealt),
//   actions: [[seat, action, amount, street, fault], ...], end, res, net.
// Amounts: blinds, call and bet are chips ADDED; raise_to is the TOTAL the
// player has in for that street. Stacks are rebuilt from those rules.

export const STREETS = ['preflop', 'flop', 'turn', 'river'];
const BOARD_AT = { preflop: 0, flop: 3, turn: 4, river: 5 };
const GLYPH = { s: '♠', h: '♥', d: '♦', c: '♣' };

/** "TD" -> {rank:'10', suit:'d', glyph:'♦', red:true, text:'10♦'}. */
export function parseCard(code) {
  const rank = code.slice(0, -1);
  const suit = code.slice(-1).toLowerCase();
  const shown = rank === 'T' ? '10' : rank;
  return {
    rank: shown,
    suit,
    glyph: GLYPH[suit] || '?',
    red: suit === 'h' || suit === 'd',
    text: shown + (GLYPH[suit] || '?'),
  };
}

const cap = (word) => word.charAt(0).toUpperCase() + word.slice(1);

function boardText(cards, count) {
  return cards.slice(0, count).map((c) => parseCard(c).text).join(' ');
}

/** Short label shown beside a seat after it acts. */
function shortNote(name, chips, total, allIn) {
  let text;
  switch (name) {
    case 'post_small_blind': text = `small blind ${chips}`; break;
    case 'post_big_blind': text = `big blind ${chips}`; break;
    case 'fold': return 'folds';
    case 'check': return 'checks';
    case 'call': text = `calls ${chips}`; break;
    case 'bet': text = `bets ${chips}`; break;
    case 'raise_to': text = `raises to ${total}`; break;
    default: text = name;
  }
  return allIn ? `${text} (all in)` : text;
}

/**
 * Builds the frames of a hand. Each frame is a full snapshot:
 *   {kind, text, actor, seats:[{stack, bet, folded, allIn, note}], pot,
 *    board, street, faceUp, fault}
 * `opts.reveal` is the export's reveal mode ('showdown' or 'all').
 */
export function buildFrames(hand, opts = {}) {
  const n = hand.seats.length;
  const names = hand.seats;
  const stacks = hand.stacks.slice();
  const bets = new Array(n).fill(0);
  const folded = new Array(n).fill(false);
  const allIn = new Array(n).fill(false);
  const notes = new Array(n).fill('');
  const haveHole = Array.isArray(hand.hole);
  const alwaysUp = haveHole && opts.reveal === 'all';
  let pot = 0;
  let street = 'preflop';
  let board = 0;
  const frames = [];

  const snap = (extra) => ({
    kind: 'action',
    text: '',
    actor: null,
    seats: stacks.map((stack, i) => ({
      stack,
      bet: bets[i],
      folded: folded[i],
      allIn: allIn[i],
      note: notes[i],
    })),
    pot,
    board,
    street,
    faceUp: alwaysUp,
    fault: false,
    ...extra,
  });

  frames.push(
    snap({ kind: 'start', text: `New hand: blinds ${hand.sb}/${hand.bb}` }),
  );

  const dealTo = (next) => {
    street = next;
    bets.fill(0);
    notes.fill('');
    board = BOARD_AT[next];
    const cards = boardText(hand.board, board);
    frames.push(snap({ kind: 'street', text: `${cap(next)}: ${cards}` }));
  };

  for (const [seat, name, amount, actionStreet, fault] of hand.actions) {
    if (actionStreet !== street) dealTo(actionStreet);
    let chips = 0;
    if (name === 'raise_to') chips = (amount ?? 0) - bets[seat];
    else if (['post_small_blind', 'post_big_blind', 'call', 'bet'].includes(name)) {
      chips = amount ?? 0;
    }
    chips = Math.max(0, Math.min(chips, stacks[seat]));
    stacks[seat] -= chips;
    bets[seat] += chips;
    pot += chips;
    if (name === 'fold') folded[seat] = true;
    if (stacks[seat] === 0 && chips > 0) allIn[seat] = true;
    notes[seat] = shortNote(name, chips, bets[seat], allIn[seat]);
    frames.push(
      snap({
        kind: name.startsWith('post_') ? 'blind' : 'action',
        actor: seat,
        text: `${names[seat]} ${notes[seat]}`,
        fault: Boolean(fault),
      }),
    );
  }

  // An all-in call ends the betting early: deal the rest of the board.
  if (hand.end === 'showdown') {
    for (const next of STREETS.slice(1)) {
      if (BOARD_AT[next] > board && BOARD_AT[next] <= hand.board.length) {
        dealTo(next);
      }
    }
  }

  // Final frame: settle the pot. Stacks come from the engine's own result,
  // which already includes any uncalled bet handed back.
  const final = hand.stacks.map((stack, i) => stack + hand.net[i]);
  const finalNotes = hand.res.map(([won, label], i) => {
    if (hand.end === 'fold') return won > 0 ? `wins ${won}` : 'folded';
    return won > 0 ? `wins ${won} · ${label}` : label || '';
  });
  const winners = hand.res
    .map(([won, label], i) => ({ i, won, label }))
    .filter((r) => r.won > 0);
  let result;
  if (hand.end === 'fold' && winners.length === 1) {
    const loser = names.find((_, i) => i !== winners[0].i);
    result = `${names[winners[0].i]} wins ${winners[0].won}: ${loser} folded`;
  } else if (winners.length === 1) {
    result = `${names[winners[0].i]} wins ${winners[0].won} with ${winners[0].label}`;
  } else {
    result = `Split pot: ${winners.map((w) => `${names[w.i]} ${w.won}`).join(', ')}`;
  }
  frames.push({
    kind: 'end',
    text: result,
    actor: null,
    seats: final.map((stack, i) => ({
      stack,
      bet: 0,
      folded: folded[i],
      allIn: false,
      note: finalNotes[i],
    })),
    pot: 0,
    board,
    street,
    faceUp: haveHole,
    fault: false,
    result,
  });
  return frames;
}

/** Self-check used by tests: chips conserved, never negative, and the
 *  actions agree with the engine's recorded result. */
export function checkFrames(hand, frames) {
  const total = hand.stacks.reduce((a, b) => a + b, 0);
  const problems = [];
  frames.forEach((frame, index) => {
    const held = frame.seats.reduce((sum, s) => sum + s.stack, 0);
    if (frame.kind !== 'end' && held + frame.pot !== total) {
      problems.push(`frame ${index}: ${held} + pot ${frame.pot} != ${total}`);
    }
    if (frame.kind === 'end' && held !== total) {
      problems.push(`end frame holds ${held}, expected ${total}`);
    }
    frame.seats.forEach((seat, i) => {
      if (seat.stack < 0) problems.push(`frame ${index}: seat ${i} negative`);
    });
  });
  // Independent of the action rules above: the engine's result says how many
  // chips each seat must have put in (winnings minus net, uncalled bets
  // included). The actions have to add up to exactly that.
  const beforeSettle = frames[frames.length - 2];
  hand.res.forEach(([won], i) => {
    const putIn = hand.stacks[i] - beforeSettle.seats[i].stack;
    if (putIn !== won - hand.net[i]) {
      problems.push(
        `seat ${i} put in ${putIn} by the actions but ${won - hand.net[i]} by the result`,
      );
    }
  });
  const last = frames[frames.length - 1];
  hand.net.forEach((delta, i) => {
    if (last.seats[i].stack !== hand.stacks[i] + delta) {
      problems.push(`seat ${i} final stack disagrees with net ${delta}`);
    }
  });
  return problems;
}

/** Whose chips swung most, from bot A's side. */
export function swingFor(hand, aName) {
  const index = hand.seats.indexOf(aName);
  return index === -1 ? 0 : hand.net[index];
}
