// The team list of the live format: every name with its status in words.
// Names are plain text (there are no team pages in a live event).

import { h } from '../dom.js';
import { LIVE_STATUS_LEGEND, delayNotice, teamBadge, teamSummary } from '../live-core.js';

/** The names, with their status as a word beside each (not colour alone). */
export function liveRoster(teams, label) {
  return h(
    'ul',
    { class: 'roster', 'aria-label': label },
    teams.map((entry) =>
      h(
        'li',
        {},
        h('span', { class: 'name' }, entry.team),
        h('span', { class: teamBadge(entry.status).cls }, entry.status),
      ),
    ),
  );
}

/** Teams in the order that reads best: playing first, then the rest by status, each by name. */
export function orderedTeams(teams) {
  const rank = new Map([['champion', 0], ['playing', 1], ['in the lobby', 2], ['registered', 3], ['out', 4]]);
  return [...teams].sort((a, b) => (rank.get(a.status) ?? 9) - (rank.get(b.status) ?? 9) || a.team.localeCompare(b.team));
}

/** The Teams page: everyone, with a summary line and what the words mean. */
export function teamsView(ctx) {
  const teams = ctx.data.teams;
  const page = h('div', { class: 'page' }, h('header', {}, h('h1', {}, 'Teams'), h('span', { class: 'muted' }, String(teams.length))));
  page.appendChild(h('p', { class: 'note live-notice' }, delayNotice(ctx.data.live.delay_seconds)));
  if (!teams.length) {
    page.appendChild(h('div', { class: 'empty card' }, 'No teams are listed yet.'));
    return { el: page, title: 'Teams' };
  }
  const summary = teamSummary(teams);
  page.appendChild(
    h(
      'section',
      { class: 'card', 'aria-label': 'All teams' },
      h('h2', { class: 'counted' }, 'All teams', h('span', { class: 'muted small' }, summary)),
      liveRoster(orderedTeams(teams), 'All teams'),
      h('p', { class: 'note' }, LIVE_STATUS_LEGEND),
    ),
  );
  return { el: page, title: 'Teams' };
}
