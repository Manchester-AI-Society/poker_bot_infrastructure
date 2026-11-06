// The tournament home page (#/ in tournament mode): the phase, Round 1 as one
// card per group, then the finals and the champion. Until a round is complete
// the data holds only the draw, so those parts say so in words.

import { h } from '../dom.js';
import { plural } from '../format.js';
import {
  finalMarks,
  finalsNote,
  finalsStage,
  groupMarks,
  phaseInfo,
  roundOneNote,
  groupsRevealed,
} from '../tournament-core.js';
import { leaderboardTable } from './leaderboard.js';

function teamLink(name) {
  return h('a', { href: `#/team/${encodeURIComponent(name)}` }, name);
}

/** A row of team names as links. */
export function teamChips(names, label) {
  return h('ul', { class: 'chips', 'aria-label': label }, names.map((name) => h('li', {}, teamLink(name))));
}

/** The phase in plain words. */
export function phaseBanner(t) {
  const info = phaseInfo(t.phase);
  return h(
    'section',
    { class: 'phase card', 'aria-label': 'Tournament status' },
    h('span', { class: 'badge' }, info.label),
    h('p', {}, info.text),
  );
}

/** The champion, as a banner with the word "Champion" (not colour alone). */
export function championBanner(t) {
  if (!t.champion) return null;
  return h(
    'section',
    { class: 'champion card', 'aria-label': 'Champion' },
    h('div', { class: 'k' }, h('span', { 'aria-hidden': 'true' }, '★ '), 'Champion'),
    h('div', { class: 'name' }, teamLink(t.champion)),
  );
}

/** One group: its team list before the reveal, its ranked table after. */
export function groupCard(group, t, { limit = null } = {}) {
  const count = plural(group.teams.length, 'team');
  const card = h('section', { class: 'group card', 'aria-label': `Group ${group.name}` });
  card.appendChild(h('h3', {}, `Group ${group.name}`, h('span', { class: 'muted small' }, count)));
  if (group.board) {
    card.appendChild(
      leaderboardTable(group.board, {
        limit,
        marks: groupMarks(group, t),
        caption: `Group ${group.name} ranking by mean big blinds won per hand, with 95% interval`,
      }),
    );
  } else {
    card.appendChild(teamChips(group.teams, `Teams in group ${group.name}`));
  }
  return card;
}

/** Round 1: the note, then every group. */
export function roundOneSection(t, opts = {}) {
  const section = h('section', { class: 'round', 'aria-labelledby': 'round-1' });
  section.appendChild(h('h2', { id: 'round-1' }, 'Round 1: groups'));
  const note = roundOneNote(t);
  if (note) section.appendChild(h('p', { class: 'note' }, note));
  if (!t.groups.length) return section;
  section.appendChild(
    h('div', { class: groupsRevealed(t) ? 'groups ranked' : 'groups' }, t.groups.map((g) => groupCard(g, t, opts))),
  );
  if (groupsRevealed(t)) {
    section.appendChild(
      h('p', { class: 'note' }, `Teams marked Qualified (the top ${t.advance} of each group) go through to the finals.`),
    );
  }
  return section;
}

/** Round 2: what is going to happen, the finalists, or the final table. */
export function finalsSection(t, finalBoard = null) {
  const section = h('section', { class: 'round', 'aria-labelledby': 'round-2' });
  section.appendChild(h('h2', { id: 'round-2' }, 'Round 2: finals'));
  const note = finalsNote(t);
  if (note) section.appendChild(h('p', { class: 'note' }, note));
  const stage = finalsStage(t);
  if (stage === 'known' || stage === 'playing') {
    const names = t.finals ? t.finals.teams : t.qualified;
    section.appendChild(h('div', { class: 'card' }, h('h3', {}, 'Finalists'), teamChips(names, 'Finalists')));
  } else if (stage === 'result') {
    section.appendChild(
      h(
        'div',
        { class: 'card' },
        leaderboardTable(finalBoard || t.finals.board, {
          marks: finalMarks(t),
          caption: 'Finals ranking by mean big blinds won per hand, with 95% interval',
        }),
      ),
    );
  }
  return section;
}

/** Before the draw: who has signed up (names only; no results exist yet). */
function registeredCard(teams) {
  if (!teams.length) return null;
  return h(
    'section',
    { class: 'card', 'aria-label': 'Registered teams' },
    h('h3', {}, 'Registered teams', h('span', { class: 'muted small' }, String(teams.length))),
    teamChips(teams.map((entry) => entry.team), 'Registered teams'),
  );
}

const SCORE_NOTE =
  'Score is the mean number of big blinds won per hand against every opponent in the round, ' +
  'each opponent counting equally. Every deal is played twice with the seats swapped, which ' +
  'removes most card luck. The bar shows the 95% interval: if it crosses zero or touches ' +
  'the next team’s, the order is not certain.';

export function tournamentView(ctx) {
  const t = ctx.data.tournament;
  const page = h(
    'div',
    { class: 'page' },
    h('header', {}, h('h1', {}, 'Tournament')),
    phaseBanner(t),
    championBanner(t),
    t.phase === 'registration' && !t.groups.length ? registeredCard(ctx.data.teams) : null,
    roundOneSection(t),
    finalsSection(t, ctx.data.boards.final),
    groupsRevealed(t) ? h('p', { class: 'note' }, SCORE_NOTE) : null,
  );
  return { el: page, title: 'Tournament' };
}
