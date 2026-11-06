// TV mode in the live format: a hands-off, full-screen view of the table
// that is on now, with big type. With several tables it moves to the next
// table that is still playing every so often; it also follows the feed when
// new data arrives, and shows the champion at the end.

import { data } from '../api.js';
import { h } from '../dom.js';
import { allTables, chooseShown, delayNotice, statusBanner } from '../live-core.js';
import { playbackFor } from '../live-playback-core.js';
import { tableStage } from './live-table.js';

const ROTATE_SECONDS = 45;
const WATCH_MS = 1000;

export function liveTvView() {
  const wrap = h('div', { class: 'tvwrap livetv' });
  const title = h('h1', {});
  const badge = h('span', { class: 'badge' });
  const notice = h('p', { class: 'live-notice' });
  const body = h('div', { class: 'tvbody' });
  const exit = h('a', { class: 'tvexit', href: '#/' }, 'Exit TV mode (Esc)');
  wrap.append(h('div', { class: 'tvhead' }, title, badge), notice, body, exit);
  document.documentElement.classList.add('tv');

  let stage = null;
  let shown = null;
  let since = Date.now();
  let version = null;
  let champion = null;

  function entries() {
    return allTables(data.live).filter((e) => data.tables[e.table.match_id]);
  }

  /** The table to show: stay on the current one for a while, then the next one still playing. */
  function pick() {
    const list = entries();
    if (!list.length) return null;
    const playing = list.filter((e) => e.table.status === 'playing');
    const current = list.find((e) => e.table.match_id === shown);
    const rotate = Date.now() - since > ROTATE_SECONDS * 1000;
    if (current && !rotate && (current.table.status === 'playing' || playbackFor(shown).state() !== 'finished')) return shown;
    const pool = playing.length ? playing : list;
    if (current && rotate && pool.length > 1) {
      const at = pool.findIndex((e) => e.table.match_id === shown);
      return pool[(at + 1) % pool.length].table.match_id;
    }
    return chooseShown(data.live, data.tables, { current: shown, finishedAndSeen: (id) => playbackFor(id).state() === 'finished' });
  }

  function draw() {
    const live = data.live;
    const id = pick();
    const banner = statusBanner(live);
    badge.textContent = banner.label;
    notice.textContent = delayNotice(live.delay_seconds);
    if (id !== shown || !stage) {
      if (stage) stage.dispose();
      stage = null;
      shown = id;
      since = Date.now();
      body.replaceChildren();
      if (id) {
        const entry = entries().find((e) => e.table.match_id === id);
        title.textContent = `Live · ${entry.label}`;
        stage = tableStage({ id, label: entry.label, compact: true });
        body.appendChild(stage.el);
      } else {
        title.textContent = 'Live';
        body.appendChild(h('p', { class: 'empty' }, banner.text));
      }
    }
    if (live.champion !== champion) {
      champion = live.champion;
      const old = body.querySelector('.champion');
      if (old) old.remove();
      if (champion) {
        body.prepend(
          h('section', { class: 'champion card', 'aria-label': 'Champion' }, h('div', { class: 'k' }, h('span', { 'aria-hidden': 'true' }, '★ '), 'Champion'), h('div', { class: 'name' }, champion)),
        );
      }
    }
  }

  function watch() {
    // New data from the poll: the page does not redraw this view, so follow it here.
    const next = data.manifest ? data.manifest.fingerprint : null;
    if (next !== version) {
      version = next;
      if (data.live) draw();
      if (stage) stage.sync();
    } else if (data.live) {
      const id = pick();
      if (id !== shown) draw();
    }
  }

  function onKey(event) {
    if (event.key === 'Escape') location.hash = '#/';
  }
  document.addEventListener('keydown', onKey);
  const timer = setInterval(watch, WATCH_MS);
  draw();
  version = data.manifest ? data.manifest.fingerprint : null;

  return {
    el: wrap,
    title: 'TV mode',
    dispose() {
      clearInterval(timer);
      if (stage) stage.dispose();
      document.removeEventListener('keydown', onKey);
      document.documentElement.classList.remove('tv');
    },
  };
}
