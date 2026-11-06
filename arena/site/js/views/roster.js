// The list of team names with their status, shared by the tournament home page
// and the Register page. Names only: no results are ever shown here.

import { h } from '../dom.js';
import { entryStatus } from '../tournament-core.js';

const STATUS_BADGE = {
  submitted: { cls: 'badge ok', text: 'submitted' },
  registered: { cls: 'badge', text: 'registered' },
};

/** What the two status words mean, in one line (so the badges are not guesses). */
export const STATUS_LEGEND = 'submitted: the bot has arrived. registered: the name is listed, waiting for a bot.';

/**
 * The names, in the order given, each with its status as a word. A name links
 * to its team page.
 */
export function rosterList(teams, label) {
  return h(
    'ul',
    { class: 'roster', 'aria-label': label },
    teams.map((entry) => {
      const badge = STATUS_BADGE[entryStatus(entry)];
      return h(
        'li',
        {},
        h('a', { class: 'name', href: `#/team/${encodeURIComponent(entry.team)}` }, entry.team),
        h('span', { class: badge.cls }, badge.text),
      );
    }),
  );
}
