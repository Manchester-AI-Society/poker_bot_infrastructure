import { allPairings } from '../api.js';
import { h } from '../dom.js';
import { ago, buildHash, fmtBB, fmtPlain, plural } from '../format.js';
import { NOT_YET, isTournament } from '../tournament-core.js';
import { kindBadge } from './leaderboard.js';

const PAGE_SIZE = 50;
const KIND_LABEL = { all: 'All matches', final: 'Final', ladder: 'Ladder', group: 'Round 1 (groups)' };

/** The result line from the winner's side (or a neutral one for a tie). */
export function resultText(p) {
  const half = p.ci95_bb == null ? '' : ` ± ${fmtPlain(p.ci95_bb)}`;
  if (p.verdict === 'tie') {
    return `no clear winner (${fmtBB(p.mean_bb)}${half})`;
  }
  const winner = p.verdict === 'a' ? p.a : p.b;
  const margin = Math.abs(p.mean_bb);
  return `${winner} wins by ${fmtPlain(margin)}${half} bb/hand`;
}

export function matchRow(p, now) {
  const faults = [];
  if (p.faults_a) faults.push(`${p.a}: ${plural(p.faults_a, 'fault')}`);
  if (p.faults_b) faults.push(`${p.b}: ${plural(p.faults_b, 'fault')}`);
  for (const [side, name] of [['disabled_a', p.a], ['disabled_b', p.b]]) {
    if (p[side]) faults.push(`${name} was replaced by an always-fold stub`);
  }
  const winnerA = p.verdict === 'a';
  const winnerB = p.verdict === 'b';
  const team = (name, wins) =>
    h(
      'a',
      {
        href: `#/team/${encodeURIComponent(name)}`,
        class: wins ? 'win' : null,
      },
      wins ? [h('span', { class: 'sym', 'aria-hidden': 'true' }, '✓'), name] : name,
    );
  return h(
    'li',
    { class: 'mrow' },
    h('span', { class: 'when' }, p.finished_at ? ago(now / 1000 - p.finished_at) : ''),
    h('span', { class: 'vs' }, team(p.a, winnerA), ' vs ', team(p.b, winnerB)),
    h('span', { class: 'res' }, resultText(p)),
    p.replay
      ? h('a', { href: `#/replay/${p.id}` }, 'Watch hands')
      : h('span', { class: 'muted small' }, p.kind === 'final' ? '' : ' '),
    h(
      'span',
      { class: 'meta' },
      kindBadge(p.kind, p.group),
      ` ${plural(p.hands, 'hand')} (${plural(p.deals_completed, 'deal')})`,
      p.rounds > 1 ? ` · pooled over ${p.rounds} rounds` : '',
      p.status !== 'complete' ? ' · incomplete' : '',
      faults.length ? h('span', { class: 'lose' }, ` · ⚠ ${faults.join('; ')}`) : null,
    ),
  );
}

export function matchesView(ctx) {
  const tournament = isTournament(ctx.data.manifest);
  const query = { ...ctx.query };
  // The tournament has no "current" kind: show everything unless asked.
  const kind = query.kind || (tournament ? 'all' : ctx.kind);
  const team = query.team || '';
  const other = query.other || '';
  const shown = Number(query.n) || PAGE_SIZE;

  if (tournament && !ctx.data.manifest.kinds.length) {
    // Nothing has been published, so there are no matches (and no filters) to offer.
    return {
      el: h('div', { class: 'page' }, h('header', {}, h('h1', {}, 'Matches')), h('div', { class: 'empty card' }, NOT_YET)),
      title: 'Matches',
    };
  }

  const names = ctx.data.teams.map((t) => t.team);
  const go = (changes) =>
    (location.hash = buildHash(['matches'], { ...query, n: '', ...changes }));

  const kindSelect = h(
    'select',
    { id: 'f-kind', onchange: (e) => go({ kind: e.target.value }) },
    ...(tournament ? ['all', 'group', 'final'] : ['final', 'ladder', 'all'])
      .filter((k) => k === 'all' || ctx.data.pairings[k])
      .map((k) => h('option', { value: k, selected: k === kind }, KIND_LABEL[k])),
  );
  const teamSelect = h(
    'select',
    { id: 'f-team', onchange: (e) => go({ team: e.target.value, other: '' }) },
    h('option', { value: '' }, 'All teams'),
    ...names.map((n) => h('option', { value: n, selected: n === team }, n)),
  );

  let list = kind === 'all' ? allPairings() : (ctx.data.pairings[kind] || []);
  if (team) list = list.filter((p) => p.a === team || p.b === team);
  if (team && other) list = list.filter((p) => p.a === other || p.b === other);

  const page = h('div', { class: 'page' });
  page.appendChild(h('header', {}, h('h1', {}, 'Matches')));
  page.appendChild(
    h(
      'div',
      { class: 'controls' },
      h('label', { for: 'f-kind' }, 'Show ', kindSelect),
      h('label', { for: 'f-team' }, 'Team ', teamSelect),
      other
        ? h('span', {}, `against ${other} `, h('a', { href: buildHash(['matches'], { ...query, other: '', n: '' }) }, '(clear)'))
        : null,
      h('span', { class: 'muted small' }, plural(list.length, 'match')),
    ),
  );
  if (!list.length) {
    page.appendChild(h('div', { class: 'empty card' }, 'No matches yet for this selection.'));
    return { el: page, title: 'Matches' };
  }
  const now = Date.now();
  const ul = h('ul', { class: 'mlist' }, list.slice(0, shown).map((p) => matchRow(p, now)));
  page.appendChild(h('div', { class: 'card' }, ul));
  if (list.length > shown) {
    page.appendChild(
      h(
        'p',
        {},
        h('button', { type: 'button', onclick: () => go({ n: String(shown + PAGE_SIZE) }) }, `Show ${Math.min(PAGE_SIZE, list.length - shown)} more`),
      ),
    );
  }
  return { el: page, title: 'Matches' };
}
