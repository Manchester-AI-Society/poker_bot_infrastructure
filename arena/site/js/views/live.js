// The live home page (#/ in the live format) and the page of one table
// (#/table/<id>): the status in plain words, the bracket, a table that plays
// itself, and the teams. Everything shown comes from the delayed data; the
// page never claims more than the files hold.

import { h } from '../dom.js';
import { fmtChips } from '../format.js';
import {
  allTables,
  chooseShown,
  delayNotice,
  labelOf,
  LIVE_STATUS_LEGEND,
  plainCount,
  statusBanner,
  tablePlayers,
  tableStateText,
  teamSummary,
} from '../live-core.js';
import { playbackFor } from '../live-playback-core.js';
import { tableStage } from './live-table.js';
import { liveRoster, orderedTeams } from './live-teams.js';

const PLAYER_ROWS = 12;

// What the visitor picked and what is being shown survive a redraw of the page.
let userChoice = null;
let shownId = null;

export function noticeEl(live) {
  return h('p', { class: 'live-notice', role: 'note' }, h('span', { 'aria-hidden': 'true' }, '⏱ '), delayNotice(live.delay_seconds));
}

function nameList(names, label) {
  return h('ul', { class: 'chips', 'aria-label': label }, names.map((name) => h('li', {}, h('span', { class: 'chip' }, name))));
}

/** The status banner: one badge and a sentence, plus who is waiting, or the champion. */
function bannerSection(live, teams) {
  const banner = statusBanner(live);
  const section = h('section', { class: 'phase card live-banner', 'aria-label': 'Status' }, h('span', { class: 'badge' }, banner.label), h('p', {}, banner.text));
  const parts = [section];
  if (live.status === 'finished' && live.champion) {
    parts.push(
      h(
        'section',
        { class: 'champion card', 'aria-label': 'Champion' },
        h('div', { class: 'k' }, h('span', { 'aria-hidden': 'true' }, '★ '), 'Champion'),
        h('div', { class: 'name' }, live.champion),
      ),
    );
  }
  if (live.status === 'idle') {
    const lobby = live.lobby;
    const registered = teams.filter((t) => t.status === 'registered').map((t) => t.team);
    parts.push(
      h(
        'section',
        { class: 'card waiting', 'aria-label': 'Who is here' },
        h('h2', { class: 'counted' }, 'In the lobby', h('span', { class: 'muted small' }, String(lobby.length))),
        lobby.length ? nameList(lobby, 'In the lobby') : h('p', { class: 'note' }, 'Nobody has connected yet.'),
        h('h3', {}, 'Registered', h('span', { class: 'muted small' }, String(registered.length))),
        registered.length ? nameList(registered, 'Registered') : h('p', { class: 'note' }, 'No names are registered yet.'),
        h('p', { class: 'note' }, 'Bots in the lobby when the tournament starts get a seat. ', h('a', { href: '#/info' }, 'How to connect'), '.'),
      ),
    );
  }
  return parts;
}

function roundTitle(round, tables) {
  return tables.length === 1 && round.round > 1 ? 'Final' : `Round ${round.round}`;
}

function tableCard(entry) {
  const { table, label } = entry;
  const players = tablePlayers(table).sort((a, b) => (b.chips ?? -1) - (a.chips ?? -1));
  const shown = players.slice(0, PLAYER_ROWS);
  const level = table.level ? ` · blinds ${fmtChips(table.level.small)}/${fmtChips(table.level.big)}` : '';
  return h(
    'article',
    { class: `tcard card${table.status === 'finished' ? ' done' : ''}`, 'aria-label': label },
    h(
      'h4',
      { class: 'tc-title' },
      h('a', { href: `#/table/${encodeURIComponent(table.match_id)}` }, label),
      h('span', { class: table.status === 'finished' ? 'badge' : 'badge ok' }, table.status),
    ),
    h(
      'ul',
      { class: 'tc-players', 'aria-label': `${label} players` },
      shown.map((p) =>
        h(
          'li',
          { class: p.state ? `is-${p.state}` : '' },
          h('span', { class: 'name', title: p.name }, p.name),
          p.state ? h('span', { class: p.state === 'winner' ? 'badge final mark' : 'badge prov' }, p.state) : null,
          h('span', { class: 'num' }, p.chips === null ? '—' : fmtChips(p.chips)),
        ),
      ),
    ),
    players.length > shown.length ? h('p', { class: 'note' }, `and ${plainCount(players.length - shown.length, 'more player')}`) : null,
    h('p', { class: 'note tc-meta' }, `${tableStateText(table)} · ${plainCount(table.hands_played, 'hand')}${level}`),
    h('a', { class: 'tc-watch', href: `#/table/${encodeURIComponent(table.match_id)}` }, 'Watch this table'),
  );
}

/** The bracket: one row of table cards for each round. */
function bracketSection(live) {
  const section = h('section', { class: 'bracket', 'aria-labelledby': 'bracket-h' }, h('h2', { id: 'bracket-h' }, 'Tables'));
  if (!live.rounds.length) {
    section.appendChild(h('p', { class: 'note' }, 'No tables yet. They appear here once play begins.'));
    return section;
  }
  const entries = allTables(live);
  for (const round of live.rounds) {
    section.appendChild(
      h(
        'div',
        { class: 'bracket-round' },
        h('h3', {}, roundTitle(round, round.tables), h('span', { class: 'muted small' }, plainCount(round.tables.length, 'table'))),
        h(
          'div',
          { class: 'tcards' },
          entries.filter((e) => e.round === round.round).map(tableCard),
        ),
      ),
    );
  }
  return section;
}

function switchLabel(live, entry) {
  return live.rounds.length > 1 && !entry.label.startsWith('Final') ? `R${entry.round} ${entry.label}` : entry.label;
}

/** The "Now showing" panel: a table that plays itself, with a switch when there are several. */
function nowShowing(ctx) {
  const { live } = ctx.data;
  const panel = h('section', { class: 'card now', 'aria-labelledby': 'now-h' });
  const body = h('div', { class: 'now-body' });
  let stage = null;

  function show(id) {
    shownId = id;
    if (stage) stage.dispose();
    stage = null;
    paint();
  }

  function paint() {
    const entries = allTables(live).filter((e) => ctx.data.tables[e.table.match_id]);
    const heading = h('h2', { id: 'now-h' }, 'Now showing');
    if (!entries.length) {
      panel.replaceChildren(heading, h('p', { class: 'empty' }, 'No table is on screen yet. A table appears here once its first hands are visible.'));
      return;
    }
    const entry = entries.find((e) => e.table.match_id === shownId) || entries[0];
    stage = tableStage({ id: entry.table.match_id, label: entry.label });
    const children = [h('div', { class: 'now-head' }, heading, h('span', { class: 'muted' }, entry.label), h('a', { class: 'small', href: `#/table/${encodeURIComponent(entry.table.match_id)}` }, 'Open on its own page'))];
    if (entries.length > 1) {
      children.push(
        h(
          'div',
          { class: 'tswitch', role: 'group', 'aria-label': 'Choose a table' },
          entries.map((e) =>
            h(
              'button',
              {
                type: 'button',
                'aria-pressed': String(e.table.match_id === entry.table.match_id),
                onclick: () => {
                  userChoice = e.table.match_id;
                  show(e.table.match_id);
                },
              },
              switchLabel(live, e),
            ),
          ),
        ),
      );
    }
    children.push(stage.el);
    panel.replaceChildren(...children);
  }

  const pick = () =>
    chooseShown(live, ctx.data.tables, {
      choice: userChoice,
      current: shownId,
      finishedAndSeen: (id) => playbackFor(id).state() === 'finished',
    });
  shownId = pick();
  paint();
  // Carry on to the next table by itself when this one has been watched to its end.
  const watcher = setInterval(() => {
    const next = pick();
    if (next && next !== shownId) show(next);
  }, 2000);
  return {
    el: panel,
    dispose() {
      clearInterval(watcher);
      if (stage) stage.dispose();
    },
  };
}

/** The home page of the live format. */
export function liveHomeView(ctx) {
  const { live } = ctx.data;
  const teams = ctx.data.teams;
  const now = nowShowing(ctx);
  const page = h('div', { class: 'page' }, h('header', {}, h('h1', {}, 'Live'), h('span', { class: 'muted' }, ctx.data.manifest.title)));
  page.append(...bannerSection(live, teams), noticeEl(live), bracketSection(live), now.el);
  if (teams.length) {
    page.appendChild(
      h(
        'section',
        { class: 'card', 'aria-label': 'Teams' },
        h('h2', { class: 'counted' }, 'Teams', h('span', { class: 'muted small' }, teamSummary(teams))),
        liveRoster(orderedTeams(teams), 'Teams'),
        h('p', { class: 'note' }, LIVE_STATUS_LEGEND),
      ),
    );
  }
  return { el: page, title: 'Live', dispose: now.dispose };
}

/** #/table/<id>: one table on its own page. */
export function liveTableView(ctx) {
  const { live } = ctx.data;
  const id = ctx.path[1];
  const entry = allTables(live).find((e) => e.table.match_id === id);
  const page = h('div', { class: 'page' });
  if (!entry) {
    page.append(
      h('header', {}, h('h1', {}, 'Table')),
      h('div', { class: 'empty card' }, 'That table is not in the feed. ', h('a', { href: '#/live' }, 'Back to the live page')),
    );
    return { el: page, title: 'Table' };
  }
  const { table, label } = entry;
  page.append(
    h(
      'header',
      {},
      h('h1', {}, label),
      h('span', { class: 'badge' }, `Round ${entry.round}`),
      h('span', { class: table.status === 'finished' ? 'badge' : 'badge ok' }, table.status),
      h('a', { class: 'small', href: '#/live' }, 'All tables'),
    ),
    noticeEl(live),
  );
  const stage = tableStage({ id, label });
  page.appendChild(h('div', { class: 'card now' }, stage.el));
  const others = allTables(live).filter((e) => e.table.match_id !== id);
  if (others.length) {
    page.appendChild(
      h(
        'section',
        { class: 'card', 'aria-label': 'Other tables' },
        h('h2', {}, 'Other tables'),
        h('ul', { class: 'chips' }, others.map((e) => h('li', {}, h('a', { href: `#/table/${encodeURIComponent(e.table.match_id)}` }, `${switchLabel(live, e)}`)))),
      ),
    );
  }
  return { el: page, title: labelOf(live, id), dispose: () => stage.dispose() };
}
