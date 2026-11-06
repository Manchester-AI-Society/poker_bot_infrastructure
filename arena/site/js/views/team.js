import { boardRow, teamEntry } from '../api.js';
import { h } from '../dom.js';
import { ago, fmtBB, fmtPlain, plural, shortHash, syncProblemText } from '../format.js';
import { NOT_YET, isTournament, teamStanding } from '../tournament-core.js';
import { kindBadge } from './leaderboard.js';

/** One opponent's result seen from `me`'s side (signs flip when me is B). */
function fromSide(p, me) {
  const isA = p.a === me;
  const sign = isA ? 1 : -1;
  const verdict = p.verdict === 'tie' ? 'draw' : (p.verdict === 'a') === isA ? 'win' : 'loss';
  return {
    other: isA ? p.b : p.a,
    mean: p.mean_bb == null ? null : sign * p.mean_bb,
    ci: p.ci95_bb,
    verdict,
    faults: isA ? p.faults_a : p.faults_b,
    stub: isA ? p.disabled_a : p.disabled_b,
    pairing: p,
  };
}

const WORD = { win: 'Won', draw: 'No clear winner', loss: 'Lost' };

/** The results table: one row per opponent, from `name`'s side. */
function resultsTable(pairings, name) {
  const results = pairings.map((p) => fromSide(p, name)).sort((x, y) => (y.mean ?? -Infinity) - (x.mean ?? -Infinity));
  return h(
    'div',
    { class: 'card tablewrap' },
    h(
      'table',
      { class: 'tbl' },
      h(
        'thead',
        {},
        h(
          'tr',
          {},
          h('th', {}, 'Opponent'),
          h('th', {}, 'Result'),
          h('th', { class: 'num' }, 'bb/hand'),
          h('th', { class: 'num' }, '95% ±'),
          h('th', { class: 'num' }, 'Hands'),
          h('th', { class: 'num' }, 'Faults'),
          h('th', {}, ''),
        ),
      ),
      h(
        'tbody',
        {},
        results.map((r) =>
          h(
            'tr',
            {},
            h('td', { class: 'team' }, h('a', { href: `#/team/${encodeURIComponent(r.other)}` }, r.other)),
            h(
              'td',
              {},
              h('span', { class: r.verdict === 'win' ? 'win' : r.verdict === 'loss' ? 'lose' : 'muted' }, WORD[r.verdict]),
            ),
            h('td', { class: 'num' }, fmtBB(r.mean)),
            h('td', { class: 'num muted' }, r.ci == null ? '—' : fmtPlain(r.ci)),
            h('td', { class: 'num' }, r.pairing.hands),
            h('td', { class: 'num' }, r.faults + (r.stub ? ' ⚠' : '')),
            h('td', {}, r.pairing.replay ? h('a', { href: `#/replay/${r.pairing.id}` }, 'Watch hands') : ''),
          ),
        ),
      ),
    ),
  );
}

const stat = (value, label) =>
  h('div', { class: 'stat' }, h('div', { class: 'v' }, value), h('div', { class: 'k' }, label));

/** Tournament format: the team's group, and its results once a round is out. */
function tournamentTeamView(ctx, name, entry) {
  const t = ctx.data.tournament;
  const me = teamStanding(name, t);
  const mine = (kind) => (ctx.data.pairings[kind] || []).filter((p) => p.a === name || p.b === name);
  const page = h('div', { class: 'page' });
  page.appendChild(
    h(
      'header',
      {},
      h('h1', {}, name),
      me.group ? h('span', { class: 'badge' }, `GROUP ${me.group}`) : null,
      me.champion ? h('span', { class: 'badge final mark' }, h('span', { 'aria-hidden': 'true' }, '★'), 'Champion') : null,
      me.qualified && t.rounds !== 1 ? h('span', { class: 'badge ok' }, h('span', { 'aria-hidden': 'true' }, '✓'), 'Qualified for the finals') : null,
    ),
  );
  if (!ctx.data.manifest.kinds.length) {
    page.appendChild(
      h(
        'p',
        {},
        me.group ? `${name} is in group ${me.group} (${plural(me.groupSize, 'team')}). ` : `${name} has not been drawn into a group yet. `,
        NOT_YET,
      ),
    );
    return { el: page, title: name };
  }

  const row = me.groupRow;
  page.appendChild(
    h(
      'div',
      { class: 'stats' },
      stat(me.group ? `Group ${me.group}` : '–', 'round 1 group'),
      stat(row && row.score != null ? `#${row.rank}` : '–', 'rank in group'),
      stat(row ? fmtBB(row.score) : '—', 'bb/hand'),
      stat(row ? `${row.wins}–${row.draws}–${row.losses}` : '—', 'W–D–L'),
      t.rounds === 1 ? null : stat(me.qualified == null ? '—' : me.qualified ? 'Yes' : 'No', 'in the finals'),
    ),
  );
  for (const [kind, heading] of [
    ['group', 'Round 1 results against each team'],
    ['final', 'Finals results against each team'],
  ]) {
    const pairings = mine(kind);
    if (!pairings.length) continue;
    page.appendChild(h('h2', {}, heading));
    page.appendChild(resultsTable(pairings, name));
  }
  if (me.finalRow) {
    page.appendChild(
      h('p', { class: 'note' }, `Finals: ranked #${me.finalRow.rank}, ${fmtBB(me.finalRow.score)} bb/hand, record ${me.finalRow.wins}–${me.finalRow.draws}–${me.finalRow.losses}.`),
    );
  }
  return { el: page, title: name };
}

export function teamView(ctx) {
  const name = ctx.path[1];
  const entry = teamEntry(name);
  const page = h('div', { class: 'page' });
  if (!entry) {
    page.appendChild(h('header', {}, h('h1', {}, 'Team not found')));
    page.appendChild(
      h('p', {}, `There is no team called “${name}”. `, h('a', { href: '#/' }, 'Back to the leaderboard')),
    );
    return { el: page, title: 'Team not found' };
  }
  if (isTournament(ctx.data.manifest)) return tournamentTeamView(ctx, name, entry);

  const row = boardRow(ctx.kind, name);
  page.appendChild(h('header', {}, h('h1', {}, name), kindBadge(ctx.kind)));
  const fetchProblem = syncProblemText(entry.sync);
  if (fetchProblem) {
    page.appendChild(
      h('div', { class: 'card' }, h('span', { class: 'lose' }, '⚠️ Fetch problem: '), fetchProblem),
    );
  }

  page.appendChild(
    h(
      'div',
      { class: 'stats' },
      stat(row && row.score != null ? `#${row.rank}` : '–', 'rank'),
      stat(row ? fmtBB(row.score) : '—', 'bb/hand'),
      stat(row && row.ci95 != null ? `± ${fmtPlain(row.ci95)}` : '—', '95% interval'),
      stat(row ? `${row.wins}–${row.draws}–${row.losses}` : '—', 'W–D–L'),
      stat(row ? String(row.faults) : '—', 'bot faults'),
    ),
  );
  if (!row) {
    page.appendChild(
      h('p', { class: 'note' }, ctx.kind === 'final' ? 'This team is not in the final.' : 'This team has no valid bot in the ladder yet.'),
    );
  }

  const pairings = (ctx.data.pairings[ctx.kind] || []).filter((p) => p.a === name || p.b === name);
  if (pairings.length) {
    page.appendChild(h('h2', {}, 'Results against each team'));
    page.appendChild(resultsTable(pairings, name));
  }

  page.appendChild(h('h2', {}, 'Submitted versions'));
  const versions = [...entry.versions].reverse();
  const now = Date.now() / 1000;
  page.appendChild(
    h(
      'ul',
      { class: 'card versions' },
      versions.map((v) =>
        h(
          'li',
          {},
          h('span', { class: `badge ${v.status === 'valid' ? 'ok' : 'bad'}` }, v.status === 'valid' ? '✓ valid' : '✗ invalid'),
          h('span', { class: 'mono' }, shortHash(v.hash)),
          h('span', { class: 'muted small' }, ago(now - v.created_at)),
          v.hash === entry.current ? h('span', { class: 'badge' }, 'current') : null,
          v.hash === entry.frozen ? h('span', { class: 'badge final' }, 'in the final') : null,
          v.message ? h('span', { class: 'muted small' }, v.message) : null,
        ),
      ),
    ),
  );
  page.appendChild(
    h('p', { class: 'note' }, `${plural(entry.versions.length, 'version')} submitted. A failed submission never replaces a working bot.`),
  );
  return { el: page, title: name };
}
