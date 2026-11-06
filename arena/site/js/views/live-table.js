// The live table: an oval with seats round it (a list of seats when the
// screen is too narrow), the board and pot in the middle, controls, and the
// log of the hand being played. All of it is drawn from the Playback of one
// table (live-playback-core.js); this file only paints and keeps time.
//
// Hole cards are drawn only from a frame's `hole` (set only at a showdown, for
// the players the data names): a seat otherwise shows two card backs.

import { data } from '../api.js';
import { h } from '../dom.js';
import { fmtChips } from '../format.js';
import { delayText, playbackStatus, seatStatus } from '../live-core.js';
import { SPEEDS, STREET_LABEL, playbackFor } from '../live-playback-core.js';
import { chooseLayout } from '../table-layout-core.js';
import { cardBack, cardEl, cardSlot } from './cards.js';

const TICK_MS = 100;
const MAX_DT = 1500; // a tab asleep for a minute must not fast-forward the table

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

function rootScale() {
  const px = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return Number.isFinite(px) && px > 0 ? px / 16 : 1;
}

function seatEl(seat, index, frame, size, ring, position) {
  const toAct = frame.next === index;
  const status = seatStatus(seat, toAct);
  const classes = ['lt-seat', `s-${size.name}`, `st-${seat.state}`];
  if (toAct) classes.push('to-act');
  if (frame.actor === index) classes.push('acted');
  if (seat.winner) classes.push('winner');
  const style = ring
    ? `width:${size.w}px;height:${size.h}px;left:${Math.round(position.x - size.w / 2)}px;top:${Math.round(position.y - size.h / 2)}px;font-size:${size.font}px`
    : `font-size:${size.font}px`;
  const faceUp = Boolean(seat.hole);
  const inHand = seat.state === 'in' || seat.state === 'allin' || faceUp;
  const cards = h('div', { class: 'lt-cards', 'aria-hidden': inHand ? null : 'true' });
  if (faceUp) cards.append(...seat.hole.map(cardEl));
  else if (inHand) cards.append(cardBack(), cardBack());
  const tags = [];
  if (seat.dealer) tags.push(h('span', { class: 'lt-dealer', title: 'Dealer button', 'aria-label': 'dealer' }, 'D'));
  if (seat.blind === 'SB' || seat.blind === 'BB') tags.push(h('span', { class: 'lt-blind', title: seat.blind === 'SB' ? 'Small blind' : 'Big blind' }, seat.blind));
  const label = `${seat.name}: ${fmtChips(seat.stack)} chips${status.text ? `, ${status.text}` : ''}${status.bet ? `, bet ${fmtChips(status.bet)}` : ''}${seat.dealer ? ', dealer' : ''}`;
  return h(
    'div',
    { class: classes.join(' '), style, role: 'group', 'aria-label': label },
    h(
      'div',
      { class: 'lt-nm' },
      toAct ? h('span', { class: 'lt-arrow', 'aria-hidden': 'true' }, '▶') : null,
      h('span', { class: 'lt-name', title: seat.name }, seat.name),
      tags,
    ),
    h('div', { class: 'lt-row' }, cards, h('span', { class: 'lt-chips num' }, fmtChips(seat.stack))),
    h(
      'div',
      { class: 'lt-st' },
      h('span', { class: 'lt-say-seat' }, status.text),
      status.bet ? h('span', { class: 'lt-bet num' }, `bet ${fmtChips(status.bet)}`) : null,
    ),
  );
}

function centerEl(frame, previous) {
  const slots = [];
  for (let i = 0; i < 5; i += 1) {
    if (i < frame.board.length) {
      const el = cardEl(frame.board[i]);
      const fresh = previous && previous.n === frame.n && i >= previous.board.length;
      if (fresh && !reducedMotion()) el.classList.add('deal');
      slots.push(el);
    } else slots.push(cardSlot());
  }
  const pot = frame.potWon > 0 && frame.pot === 0 ? `Pot won ${fmtChips(frame.potWon)}` : `Pot ${fmtChips(frame.pot)}`;
  return h(
    'div',
    { class: 'lt-center' },
    h('div', { class: 'lt-board', 'aria-label': 'Board' }, slots),
    h('div', { class: 'lt-pot num' }, pot),
    h('div', { class: 'lt-say' }, frame.text),
  );
}

/**
 * The table viewer for one table. Options:
 *   id        the match id (a key of data.tables)
 *   label     the name shown in the header ("Table 2")
 *   compact   TV mode: no controls, bigger type
 * Returns {el, dispose, sync, playback}. `sync()` feeds new data to the
 * playback; the page calls it when the data has changed.
 */
export function tableStage({ id, label = '', compact = false }) {
  const pb = playbackFor(id);
  const stage = h('section', { class: `lt${compact ? ' tv' : ''}`, 'aria-label': label ? `${label}: poker table` : 'Poker table' });
  const head = h('div', { class: 'lt-head' });
  const wrap = h('div', { class: 'lt-wrap' });
  const status = h('p', { class: 'lt-status note', role: 'status' });
  const log = h('ol', { class: 'lt-log', 'aria-label': 'What happened in this hand' });

  const pause = h('button', { type: 'button', class: 'lt-pause', onclick: () => { pb.togglePause(); paint(true); } }, 'Pause');
  const speedButtons = SPEEDS.map((s) =>
    h('button', { type: 'button', 'data-speed': String(s), 'aria-label': `Speed ${s}×`, onclick: () => { pb.setSpeed(s); paint(true); } }, `${s}×`),
  );
  const live = h('button', { type: 'button', class: 'lt-live', onclick: () => { pb.jumpToLive(); paint(true); } }, 'Jump to live');
  const controls = h('div', { class: 'lt-controls' }, pause, h('div', { class: 'seg', role: 'group', 'aria-label': 'Playback speed' }, speedButtons), live);

  stage.append(head, wrap);
  if (!compact) stage.append(controls);
  stage.append(status);
  // The TV view is for reading from across a room: the middle line says what just happened.
  if (!compact) stage.append(h('h3', { class: 'lt-log-h' }, 'This hand'), log);

  let timer = null;
  let last = Date.now();
  let shown = { key: '', frame: null, width: 0 };
  let resizer = null;

  function table() {
    return data.tables[id] || null;
  }

  function sync() {
    const t = table();
    const before = pb.version;
    pb.feed(t ? t.hands : [], { version: `${data.manifest ? data.manifest.fingerprint : ''}`, finished: Boolean(t && t.status === 'finished') });
    if (pb.version !== before || !shown.frame) paint(true);
  }

  function paintStatus() {
    const t = table();
    const state = pb.state();
    const words = playbackStatus({
      state,
      behind: pb.unseen(),
      catchUp: pb.catchUp(),
      delay: data.live ? data.live.delay_seconds : null,
      winners: t ? t.winners : [],
    });
    // Only when it changed, so a screen reader is not told the same thing again.
    if (status.textContent !== words) status.textContent = words;
    const pauseText = pb.paused ? 'Resume' : 'Pause';
    if (pause.textContent !== pauseText) pause.textContent = pauseText;
    pause.disabled = state === 'empty';
    live.disabled = state === 'empty' || pb.unseen() === 0;
    for (const button of speedButtons) button.setAttribute('aria-pressed', String(Number(button.dataset.speed) === pb.speed));
  }

  function paintTable(force) {
    const frame = pb.frame();
    const width = stage.clientWidth || (compact ? 1200 : 600);
    const key = frame ? `${frame.n}:${frame.index}` : 'none';
    if (!force && key === shown.key && Math.abs(width - shown.width) < 2) return;
    const previous = shown.key === key ? null : shown.frame;
    shown = { key, frame, width };
    if (!frame) {
      head.replaceChildren();
      const t = table();
      const delay = data.live ? delayText(data.live.delay_seconds) : '';
      wrap.replaceChildren(
        h('p', { class: 'empty' }, t ? 'No hands are visible for this table yet.' : 'This table is not in the feed yet.', delay ? ` The feed runs ${delay} behind the real game.` : ''),
      );
      log.replaceChildren();
      return;
    }
    const layout = chooseLayout(frame.seats.length, width, compact ? rootScale() : 1);
    const ring = layout.mode === 'ring';
    head.replaceChildren(
      h('span', { class: 'lt-hand' }, `Hand ${frame.n}`),
      h('span', { class: 'lt-street' }, STREET_LABEL[frame.street] || frame.street),
      frame.level ? h('span', { class: 'lt-level' }, `Blinds ${fmtChips(frame.level.small)}/${fmtChips(frame.level.big)}`) : null,
      h('span', { class: 'lt-count muted' }, `${frame.seats.length} seats`),
    );
    const seats = frame.seats.map((seat, i) => seatEl(seat, i, frame, layout.size, ring, ring ? layout.positions[i] : null));
    if (ring) {
      wrap.className = 'lt-wrap lt-ring';
      wrap.style.width = `${layout.W}px`;
      wrap.style.height = `${layout.H}px`;
      wrap.replaceChildren(
        h('div', { class: 'lt-felt', style: `left:${Math.round(layout.size.w / 2)}px;top:${Math.round(layout.size.h / 2)}px;right:${Math.round(layout.size.w / 2)}px;bottom:${Math.round(layout.size.h / 2)}px`, 'aria-hidden': 'true' }),
        centerEl(frame, previous),
        ...seats,
      );
    } else {
      wrap.className = 'lt-wrap lt-list';
      wrap.style.width = '';
      wrap.style.height = '';
      wrap.replaceChildren(h('div', { class: 'lt-felt' }, centerEl(frame, previous)), h('div', { class: 'lt-seats' }, seats));
    }
    const lines = pb.log();
    log.replaceChildren(
      ...lines.map((line, i) => h('li', { class: `lt-${line.kind}${i === lines.length - 1 ? ' latest' : ''}` }, line.text)),
    );
    if (!lines.length) log.replaceChildren(h('li', { class: 'muted' }, 'Cards are being dealt.'));
    log.scrollTop = log.scrollHeight; // the newest line stays in view
  }

  function paint(force = false) {
    paintTable(force);
    paintStatus();
  }

  function tick() {
    const now = Date.now();
    const dt = Math.min(MAX_DT, now - last);
    last = now;
    if (pb.tick(dt) > 0) paint();
    else paintStatus();
  }

  if (typeof ResizeObserver === 'function') {
    resizer = new ResizeObserver(() => paint());
    resizer.observe(stage);
  }
  timer = setInterval(tick, TICK_MS);
  sync();

  return {
    el: stage,
    playback: pb,
    sync,
    dispose() {
      clearInterval(timer);
      if (resizer) resizer.disconnect();
    },
  };
}
