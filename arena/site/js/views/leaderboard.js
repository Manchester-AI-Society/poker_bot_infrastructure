import { ciPlot, axisHeader, describeScore, scoreAxisMax } from '../charts.js';
import { h } from '../dom.js';
import { fmtBB, fmtPlain, plural } from '../format.js';

export function kindBadge(kind) {
  return kind === 'final'
    ? h('span', { class: 'badge final' }, 'FINAL')
    : h('span', { class: 'badge prov' }, 'PROVISIONAL · ladder');
}

export function emptyBoard(kind) {
  return h(
    'div',
    { class: 'empty card' },
    kind === 'final'
      ? 'The final has not produced results yet.'
      : 'No bots have been accepted yet.',
  );
}

/**
 * The ranking: score, interval plot, record and faults. `limit` shows only
 * the top N (used by TV mode).
 */
export function leaderboardTable(board, { limit = null } = {}) {
  const teams = limit ? board.teams.slice(0, limit) : board.teams;
  const max = scoreAxisMax(board.teams);
  const body = teams.map((team) => {
    const ranked = team.score != null;
    const nextRank = team.rank + 1;
    return h(
      'tr',
      {},
      h('td', { class: 'rank num' }, ranked ? team.rank : '–'),
      h(
        'td',
        { class: 'team' },
        h('a', { href: `#/team/${encodeURIComponent(team.team)}` }, team.team),
        team.tied_with_next
          ? h(
              'span',
              {
                class: 'tie',
                title: `Cannot be separated from #${nextRank} (their intervals overlap)`,
              },
              `≈ #${nextRank}`,
            )
          : null,
      ),
      h('td', { class: 'num' }, fmtBB(team.score)),
      h('td', { class: 'num muted' }, team.ci95 == null ? '—' : `± ${fmtPlain(team.ci95)}`),
      h(
        'td',
        { class: 'plotcell' },
        ciPlot({
          score: team.score,
          ci: team.ci95,
          max,
          label: describeScore(team),
        }),
      ),
      h('td', { class: 'num nowrap' }, `${team.wins}–${team.draws}–${team.losses}`),
      h('td', { class: 'num' }, faultCell(team)),
    );
  });
  return h(
    'div',
    { class: 'tablewrap' },
    h(
      'table',
      { class: 'tbl' },
      h('caption', { class: 'sr-only' }, 'Ranking by mean big blinds won per hand, with 95% interval'),
      h(
        'thead',
        {},
        h(
          'tr',
          {},
          h('th', { class: 'num', scope: 'col' }, '#'),
          h('th', { scope: 'col' }, 'Team'),
          h('th', { class: 'num', scope: 'col' }, 'bb/hand'),
          h('th', { class: 'num', scope: 'col' }, '95% ±'),
          h('th', { scope: 'col', class: 'plotcell' }, axisHeader({ max })),
          h('th', { class: 'num', scope: 'col', title: 'Wins–draws–losses, counting only statistically clear results' }, 'W–D–L'),
          h('th', { class: 'num', scope: 'col' }, 'Faults'),
        ),
      ),
      h('tbody', {}, body),
    ),
  );
}

function faultCell(team) {
  const parts = [String(team.faults)];
  if (team.disabled_in && team.disabled_in.length) {
    parts.push(
      h(
        'span',
        {
          class: 'badge bad',
          title: `Replaced by an always-fold stub in: ${team.disabled_in.join(', ')}`,
        },
        `⚠ disabled in ${team.disabled_in.length}`,
      ),
    );
  }
  return h('span', {}, ...parts.flatMap((p, i) => (i ? [' ', p] : [p])));
}

export function leaderboardView(ctx) {
  const board = ctx.data.boards[ctx.kind];
  const page = h('div', { class: 'page' });
  const head = h('header', {}, h('h1', {}, 'Leaderboard'), kindBadge(ctx.kind));
  page.appendChild(head);
  if (!board || !board.teams.length) {
    page.appendChild(emptyBoard(ctx.kind));
    return { el: page, title: 'Leaderboard' };
  }
  head.appendChild(
    h(
      'span',
      { class: 'muted small' },
      `${board.pairs_done} of ${plural(board.pairs_total, 'pairing')} played` +
        (board.cycle ? ` · cycle ${board.cycle}: every pairing is replayed each cycle and the results are added together` : ''),
    ),
  );
  if (ctx.kind === 'ladder' && ctx.data.boards.final) {
    page.appendChild(
      h('p', { class: 'note' }, 'The final has been played. ', h('a', { href: '#/?kind=final' }, 'See the final result'), '.'),
    );
  }
  page.appendChild(h('div', { class: 'card' }, leaderboardTable(board)));
  page.appendChild(
    h(
      'p',
      { class: 'note' },
      'Score is the mean number of big blinds won per hand against every opponent, ' +
        'each opponent counting equally. Every deal is played twice with the seats ' +
        'swapped, which removes most card luck. The bar shows the 95% interval: if ' +
        'it crosses zero or touches the next team’s, the order is not certain. ' +
        '≈ marks a team that cannot be separated from the one below.',
    ),
  );
  return { el: page, title: 'Leaderboard' };
}
