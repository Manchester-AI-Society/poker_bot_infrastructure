import { h } from '../dom.js';
import { ago, plural, shortHash, syncProblemText } from '../format.js';

/** Validation status of every team's bots. Read-only: submitting is done
 *  through the organiser's channel (see the text below), not on this page. */
export function submissionsView(ctx) {
  const page = h('div', { class: 'page' });
  page.appendChild(h('header', {}, h('h1', {}, 'Submissions')));

  if (ctx.data.manifest.registry_repo) {
    page.appendChild(
      h('p', {}, 'Not on the list? ', h('a', { href: '#/register' }, 'Register your team'), '.'),
    );
  }
  if (ctx.data.manifest.has_guide) {
    page.appendChild(
      h('p', {}, 'New here? ', h('a', { href: '#/submit' }, 'Read how to submit your bot'), '.'),
    );
  }
  const text = ctx.data.manifest.submit_text;
  if (text) {
    page.appendChild(
      h(
        'div',
        { class: 'card' },
        h('h2', {}, 'From the organiser'),
        h('p', { style: 'white-space:pre-wrap;margin:0' }, text),
      ),
    );
  }

  const teams = ctx.data.teams;
  if (!teams.length) {
    page.appendChild(h('div', { class: 'empty card' }, 'No submissions yet.'));
    return { el: page, title: 'Submissions' };
  }
  const now = Date.now() / 1000;
  const rows = teams.map((team) => {
    const latest = team.versions[team.versions.length - 1];
    const current = team.versions.find((v) => v.hash === team.current);
    const fetchProblem = syncProblemText(team.sync);
    const status = team.current
      ? h('span', { class: 'badge ok' }, '✓ playing')
      : h(
          'span',
          { class: 'badge bad' },
          fetchProblem ? '✗ cannot fetch repo' : '✗ no valid bot',
        );
    // Explain a failure only when the newest push is the one that failed.
    const problem = latest && latest.status !== 'valid' ? latest.message : '';
    const notes = [];
    if (fetchProblem) {
      notes.push(
        h('div', {}, h('span', { class: 'lose' }, '⚠️ Fetch problem: '), fetchProblem,
          current ? ' The previous version keeps playing.' : ''),
      );
    }
    if (problem) {
      notes.push(
        h('div', {}, h('span', { class: 'lose' }, '⚠️ Latest push failed: '), problem,
          current ? ' (the previous version keeps playing)' : ''),
      );
    }
    return h(
      'tr',
      {},
      h('td', { class: 'team' }, h('a', { href: `#/team/${encodeURIComponent(team.team)}` }, team.team)),
      h('td', {}, status),
      h('td', { class: 'mono' }, shortHash(team.current)),
      h('td', { class: 'num' }, team.versions.length),
      h('td', { class: 'muted small' }, latest ? ago(now - latest.created_at) : ''),
      h('td', { class: 'small' }, notes),
    );
  });
  page.appendChild(
    h(
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
            h('th', {}, 'Team'),
            h('th', {}, 'Status'),
            h('th', {}, 'Version'),
            h('th', { class: 'num' }, 'Versions'),
            h('th', {}, 'Last push'),
            h('th', {}, 'Notes'),
          ),
        ),
        h('tbody', {}, rows),
      ),
    ),
  );
  const playing = teams.filter((t) => t.current).length;
  page.appendChild(
    h(
      'p',
      { class: 'note' },
      `${playing} of ${plural(teams.length, 'team')} currently ${playing === 1 ? 'has' : 'have'} a valid bot. ` +
        'Each push is checked by loading the bot and playing a short match; only the last line of an error is shown here. ' +
        'The full error stays with the team.',
    ),
  );
  return { el: page, title: 'Submissions' };
}
