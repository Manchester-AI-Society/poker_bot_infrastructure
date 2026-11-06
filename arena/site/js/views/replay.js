import { findPairing, loadReplay } from '../api.js';
import { h } from '../dom.js';
import { buildHash, fmtChips, plural } from '../format.js';
import { buildFrames, parseCard, swingFor } from '../replay-core.js';
import { resultText } from './matches.js';

function cardEl(code) {
  const card = parseCard(code);
  return h(
    'span',
    { class: `card-pl${card.red ? ' red' : ''}`, 'aria-label': card.text },
    h('b', {}, card.rank),
    h('i', { 'aria-hidden': 'true' }, card.glyph),
  );
}

const cardBack = () => h('span', { class: 'card-pl back', 'aria-label': 'hidden card' });
const cardSlot = () => h('span', { class: 'card-pl empty', 'aria-hidden': 'true' });

function seatEl(index, frame, hand, replay) {
  const seat = frame.seats[index];
  const hole = hand.hole ? hand.hole[index] : null;
  const faceUp = hole && frame.faceUp;
  return h(
    'div',
    {
      class: `seat${frame.actor === index ? ' acting' : ''}${seat.folded ? ' folded' : ''}`,
    },
    h(
      'div',
      {},
      h(
        'div',
        { class: 'nm' },
        frame.actor === index ? h('span', { 'aria-hidden': 'true', class: 'mr-1' }, '▶') : null,
        hand.seats[index],
        index === hand.dealer
          ? h('span', { class: 'btn', title: 'Dealer, and small blind heads-up' }, 'D')
          : null,
      ),
      h('div', { class: 'stk' }, `Stack ${fmtChips(seat.stack)}${seat.allIn ? ' · all in' : ''}`),
      h('div', { class: 'say' }, seat.note),
    ),
    h(
      'div',
      {},
      h('div', { class: 'cards' }, faceUp ? hole.map(cardEl) : [cardBack(), cardBack()]),
      h('div', { class: 'bet num' }, seat.bet ? `Bet ${fmtChips(seat.bet)}` : ' '),
    ),
  );
}

function boardEl(frame, hand) {
  const slots = [];
  for (let i = 0; i < 5; i += 1) {
    slots.push(i < frame.board ? cardEl(hand.board[i]) : cardSlot());
  }
  return h('div', { class: 'board' }, slots);
}

/** "Deal 9", or "Deal 9 (seats swapped)" for the mirrored second play. */
export function dealLabel(hand) {
  const deal = hand.deal ?? hand.n;
  return hand.o ? `Deal ${deal} (seats swapped)` : `Deal ${deal}`;
}

function message(text) {
  const page = h('div', { class: 'page' });
  page.appendChild(h('header', {}, h('h1', {}, 'Replay')));
  page.appendChild(h('div', { class: 'empty card' }, text, ' ', h('a', { href: '#/matches' }, 'Back to matches')));
  return { el: page, title: 'Replay' };
}

/**
 * Hand replayer. `compact` hides the hand list, step log and controls (TV
 * mode); `autoplay` starts stepping at once; `onFinish` is called a moment
 * after the last frame of an autoplayed hand.
 */
export async function replayView(ctx, options = {}) {
  const { compact = false, autoplay = false, onFinish = null } = options;
  const id = ctx.path[1];
  const pairing = findPairing(id);
  if (!pairing || !pairing.replay) {
    return message(
      pairing
        ? 'Hand replays are not published for this match.'
        : 'That match is not in the results.',
    );
  }
  let replay;
  try {
    replay = await loadReplay(pairing.replay);
  } catch (error) {
    return message('The replay file could not be loaded.');
  }
  const opts = { reveal: replay.reveal };
  const state = {
    hand: Math.min(Math.max(Number(ctx.path[2]) || 0, 0), replay.hands.length - 1),
    step: 0,
    playing: autoplay,
    speed: 1,
  };
  let frames = [];
  let timer = null;
  let finishTimer = null;

  // ---- static pieces ---------------------------------------------------
  const felt = h('div', { class: 'felt' });
  const caption = h('p', { class: 'verdict', 'aria-live': 'polite' });
  const range = h('input', {
    type: 'range', min: 0, max: 1, value: 0, 'aria-label': 'Step through the hand',
    oninput: (e) => goTo(Number(e.target.value)),
  });
  const playButton = h('button', { type: 'button', onclick: () => togglePlay() }, 'Play');
  const buttons = {
    first: h('button', { type: 'button', 'aria-label': 'First step', onclick: () => goTo(0) }, '⏮'),
    prev: h('button', { type: 'button', 'aria-label': 'Previous step', onclick: () => goTo(state.step - 1) }, '◀'),
    next: h('button', { type: 'button', 'aria-label': 'Next step', onclick: () => goTo(state.step + 1) }, '▶'),
    last: h('button', { type: 'button', 'aria-label': 'Last step', onclick: () => goTo(frames.length - 1) }, '⏭'),
    prevHand: h('button', { type: 'button', onclick: () => selectHand(state.hand - 1) }, '← Hand'),
    nextHand: h('button', { type: 'button', onclick: () => selectHand(state.hand + 1) }, 'Hand →'),
  };
  const speed = h(
    'select',
    { 'aria-label': 'Playback speed', onchange: (e) => { state.speed = Number(e.target.value); if (state.playing) schedule(); } },
    [0.5, 1, 2, 4].map((v) => h('option', { value: v, selected: v === 1 }, `${v}×`)),
  );
  const stepList = h('ol', { class: 'steps' });
  const handButtons = replay.hands.map((hand, index) => {
    const swing = swingFor(hand, replay.a);
    return h(
      'button',
      { type: 'button', onclick: () => selectHand(index) },
      h(
        'span',
        {},
        h('span', {}, dealLabel(hand)),
        h('span', { class: 'muted small', style: 'display:block' }, hand.end === 'showdown' ? 'showdown' : 'ended by a fold'),
      ),
      h('span', { class: swing > 0 ? 'win num' : swing < 0 ? 'lose num' : 'num' }, `${swing > 0 ? '+' : ''}${fmtChips(swing)}`),
    );
  });

  // ---- behaviour -------------------------------------------------------
  function paint() {
    const hand = replay.hands[state.hand];
    const frame = frames[state.step];
    const aSeat = Math.max(0, hand.seats.indexOf(replay.a));
    const bSeat = hand.seats.length === 2 ? 1 - aSeat : 0;
    felt.replaceChildren(
      seatEl(bSeat, frame, hand, replay),
      h('div', {}, boardEl(frame, hand), h('div', { class: 'potline' }, frame.kind === 'end' ? ' ' : `Pot ${fmtChips(frame.pot)}`)),
      seatEl(aSeat, frame, hand, replay),
    );
    caption.textContent = frame.text + (frame.fault ? ' (bot fault: a default move was played)' : '');
    caption.className = `verdict${frame.kind === 'end' ? ' win' : ''}`;
    range.max = String(frames.length - 1);
    range.value = String(state.step);
    buttons.first.disabled = buttons.prev.disabled = state.step === 0;
    buttons.next.disabled = buttons.last.disabled = state.step === frames.length - 1;
    buttons.prevHand.disabled = state.hand === 0;
    buttons.nextHand.disabled = state.hand === replay.hands.length - 1;
    playButton.textContent = state.playing ? 'Pause' : 'Play';
    [...stepList.children].forEach((li, i) => {
      const button = li.firstChild;
      if (i === state.step) {
        button.setAttribute('aria-current', 'step');
        if (button.scrollIntoView && !compact) button.scrollIntoView({ block: 'nearest' });
      } else button.removeAttribute('aria-current');
    });
  }

  function loadHand(index, atEnd = false) {
    state.hand = index;
    const hand = replay.hands[index];
    frames = buildFrames(hand, opts);
    state.step = atEnd ? frames.length - 1 : 0;
    stepList.replaceChildren(
      ...frames.map((frame, i) =>
        h('li', {}, h('button', { type: 'button', onclick: () => goTo(i) }, `${i + 1}. ${frame.text}`)),
      ),
    );
    handButtons.forEach((b, i) =>
      i === index ? b.setAttribute('aria-current', 'true') : b.removeAttribute('aria-current'),
    );
    if (!compact) {
      history.replaceState(null, '', buildHash(['replay', id, String(index)]));
      if (handButtons[index].scrollIntoView) handButtons[index].scrollIntoView({ block: 'nearest' });
    }
  }

  function selectHand(index) {
    if (index < 0 || index >= replay.hands.length) return;
    stop();
    loadHand(index);
    paint();
  }

  function goTo(step) {
    state.step = Math.min(Math.max(step, 0), frames.length - 1);
    paint();
  }

  function stop() {
    state.playing = false;
    clearTimeout(timer);
    clearTimeout(finishTimer);
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(tick, 1300 / state.speed);
  }

  function tick() {
    if (!state.playing) return;
    if (state.step >= frames.length - 1) {
      state.playing = false;
      paint();
      if (onFinish) finishTimer = setTimeout(onFinish, 3000);
      return;
    }
    state.step += 1;
    paint();
    schedule();
  }

  function togglePlay() {
    if (state.playing) {
      stop();
    } else {
      if (state.step >= frames.length - 1) state.step = 0;
      state.playing = true;
      schedule();
    }
    paint();
  }

  function onKey(event) {
    const tag = event.target && event.target.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const keys = {
      ArrowRight: () => goTo(state.step + 1),
      ArrowLeft: () => goTo(state.step - 1),
      Home: () => goTo(0),
      End: () => goTo(frames.length - 1),
      ' ': togglePlay,
      ']': () => selectHand(state.hand + 1),
      '[': () => selectHand(state.hand - 1),
    };
    const action = keys[event.key];
    if (action) {
      event.preventDefault();
      action();
    }
  }
  document.addEventListener('keydown', onKey);

  // ---- layout ----------------------------------------------------------
  const page = h('div', { class: compact ? 'tvreplay' : 'page' });
  if (!compact) {
    page.appendChild(
      h(
        'header',
        {},
        h('h1', {}, `${pairing.a} vs ${pairing.b}`),
        h('span', { class: 'muted' }, resultText(pairing)),
      ),
    );
    page.appendChild(
      h(
        'p',
        { class: 'note', style: 'margin-top:0' },
        replay.selection === 'all'
          ? `All ${plural(replay.total_hands, 'hand')} of this match. `
          : `The ${replay.shown} biggest swings out of ${replay.total_hands.toLocaleString('en-GB')} hands. `,
        replay.reveal === 'showdown'
          ? 'Hole cards are shown only when a hand reaches showdown. '
          : 'All hole cards are shown. ',
        `${pairing.a} is always at the bottom. Every deal is played twice with the seats swapped, ` +
          'so the same cards appear in two hands. ',
        h('a', { href: `#/matches?team=${encodeURIComponent(pairing.a)}&other=${encodeURIComponent(pairing.b)}&kind=${pairing.kind}` }, 'All matches between these teams'),
      ),
    );
  }
  const stage = h('section', { class: 'stage' }, felt, caption);
  if (!compact) {
    stage.appendChild(
      h(
        'div',
        { class: 'controls-bar' },
        buttons.prevHand, buttons.first, buttons.prev, playButton, buttons.next, buttons.last, buttons.nextHand, range, speed,
      ),
    );
    stage.appendChild(h('p', { class: 'note small', style: 'margin:0.4rem 0 0' }, 'Keys: ← → step, space play or pause, [ ] previous or next hand.'));
    stage.appendChild(stepList);
  }
  if (compact) {
    page.appendChild(stage);
  } else {
    page.appendChild(
      h(
        'div',
        { class: 'replay' },
        h('aside', { class: 'card handlist' }, h('h2', { class: 'small' }, `Hands (${replay.hands.length})`), h('ol', {}, handButtons.map((b) => h('li', {}, b)))),
        stage,
      ),
    );
  }

  loadHand(state.hand);
  paint();
  if (state.playing) schedule();

  return {
    el: page,
    title: `${pairing.a} vs ${pairing.b}`,
    dispose() {
      stop();
      document.removeEventListener('keydown', onKey);
    },
  };
}
