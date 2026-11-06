import { h } from '../dom.js';
import { ago } from '../format.js';
import { registerUrl, registryIssuesUrl } from '../register-core.js';

const STATUS = {
  pending: { text: 'waiting for approval', cls: 'badge' },
  rejected: { text: 'not accepted', cls: 'badge bad' },
};

function registrationsCard(list) {
  if (!list.length) return null;
  const now = Date.now() / 1000;
  return h(
    'div',
    { class: 'card tablewrap' },
    h('h2', {}, 'Registrations that are not teams yet'),
    h(
      'table',
      { class: 'tbl' },
      h(
        'thead',
        {},
        h('tr', {}, ['Team', 'GitHub account', 'Status', 'Why'].map((t) => h('th', { scope: 'col' }, t))),
      ),
      h(
        'tbody',
        {},
        list.map((r) =>
          h(
            'tr',
            {},
            h('td', { class: 'team' }, r.team || '—'),
            h('td', {}, r.user),
            h('td', {}, h('span', { class: (STATUS[r.status] || STATUS.pending).cls }, (STATUS[r.status] || { text: r.status }).text)),
            h('td', { class: 'small' }, r.message, r.at ? h('span', { class: 'muted' }, ` (${ago(now - r.at)})`) : null),
          ),
        ),
      ),
    ),
  );
}

/**
 * Register a team: one button that opens the registration form on GitHub.
 * The arena proves the account owns the repository, and the organiser
 * approves it.
 */
export function ladderRegisterView(ctx) {
  const registry = ctx.data.manifest.registry_repo;
  const page = h('div', { class: 'page guide' });
  page.appendChild(h('header', {}, h('h1', {}, 'Register your team')));
  const form = registerUrl(registry);
  if (!form) {
    page.appendChild(h('div', { class: 'empty card' }, 'Registration is not open for this event.'));
    return { el: page, title: 'Register' };
  }

  page.appendChild(
    h(
      'div',
      { class: 'card' },
      h('p', {}, 'Your bot lives in your own ', h('strong', {}, 'public GitHub repository'), ', with ', h('code', {}, 'bot.py'), ' at the top level. Register it here once; after that, pushing to the repository updates your bot.'),
      h('a', { class: 'btn-primary', href: form, target: '_blank', rel: 'noopener noreferrer' }, 'Register on GitHub'),
      h('h2', { style: 'margin-top:1.5rem' }, 'What happens next'),
      h('ol', {},
        h('li', {}, 'GitHub opens a short form: a team name (lowercase letters, digits, “-” and “_”), your repository address, and optionally a branch. You need a GitHub account, and you must be signed in as ', h('strong', {}, 'the account that owns the repository'), ': registrations from anyone else are rejected, so nobody can register your repository for you.'),
        h('li', {}, 'Press “Submit new issue”. The arena checks it within a minute and replies on the issue, saying what is wrong if anything is.'),
        h('li', {}, 'The organiser approves it (they add an ', h('code', {}, 'approved'), ' label). Your bot is then fetched and starts playing. Watch its status on the ', h('a', { href: '#/submissions' }, 'Submissions'), ' page.'),
        h('li', {}, 'To change your repository, edit your issue, or open a new registration for the same team from the same account. To withdraw, close the issue.')),
      h('p', { class: 'note' }, 'All registrations are public: ', h('a', { href: registryIssuesUrl(registry), target: '_blank', rel: 'noopener noreferrer' }, 'see them on GitHub'), '. New here? ', h('a', { href: '#/submit' }, 'Read how to write and test a bot'), '.'),
    ),
  );
  const waiting = registrationsCard(ctx.data.registrations || []);
  if (waiting) page.appendChild(waiting);
  return { el: page, title: 'Register' };
}
