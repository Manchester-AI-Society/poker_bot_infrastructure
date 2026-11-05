import { h } from '../dom.js';
import { ago } from '../format.js';
import { buildIssueUrl, checkForm, registryIssuesUrl } from '../register-core.js';

const STATUS = {
  pending: { text: 'waiting for approval', cls: 'badge' },
  rejected: { text: 'not accepted', cls: 'badge bad' },
};

function registrationsCard(list) {
  if (!list.length) return null;
  const now = Date.now() / 1000;
  return h(
    'div',
    { class: 'card tablewrap', style: 'margin-top:1rem' },
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
 * Register a team: the form checks the details, then opens a pre-filled issue
 * in the registry on GitHub; the team presses "Submit new issue" there. The
 * arena proves the account owns the repository, and the organiser approves.
 */
export function registerView(ctx) {
  const registry = ctx.data.manifest.registry_repo;
  const page = h('div', { class: 'page guide' });
  page.appendChild(h('header', {}, h('h1', {}, 'Register your team')));
  if (!registry) {
    page.appendChild(h('div', { class: 'empty card' }, 'Registration is not open for this event.'));
    return { el: page, title: 'Register' };
  }

  const team = h('input', { type: 'text', id: 'reg-team', autocomplete: 'off', spellcheck: 'false', placeholder: 'team-fox', maxlength: '40' });
  const repo = h('input', { type: 'url', id: 'reg-repo', autocomplete: 'off', spellcheck: 'false', placeholder: 'https://github.com/your-name/your-bot' });
  const branch = h('input', { type: 'text', id: 'reg-branch', autocomplete: 'off', spellcheck: 'false', placeholder: 'main (leave empty for the default)' });
  const msg = (id) => h('div', { class: 'field-msg', id, 'aria-live': 'polite' });
  const teamMsg = msg('reg-team-msg');
  const repoMsg = msg('reg-repo-msg');
  const branchMsg = msg('reg-branch-msg');
  const go = h('a', { class: 'btn-primary', 'aria-disabled': 'true', target: '_blank', rel: 'noopener noreferrer' }, 'Open GitHub to register');
  const hint = h('p', { class: 'note', style: 'margin-top:0.5rem' });

  function update() {
    const state = checkForm({ team: team.value, repo: repo.value, branch: branch.value });
    const show = (input, box, check) => {
      const touched = input.value.trim() !== '';
      box.textContent = touched ? (check.ok ? '✓ looks good' : check.message) : '';
      box.className = `field-msg${touched ? (check.ok ? ' good' : ' bad') : ''}`;
    };
    show(team, teamMsg, state.team);
    show(repo, repoMsg, state.repo);
    show(branch, branchMsg, state.branch);
    if (state.ready) {
      go.setAttribute('href', buildIssueUrl(registry, { team: state.team.value, repo: state.repo.value, branch: state.branch.value }));
      go.setAttribute('aria-disabled', 'false');
      hint.textContent = `This opens a form on GitHub already filled in for “${state.team.value}”. Press “Submit new issue” there while signed in as ${state.repo.owner}.`;
    } else {
      go.removeAttribute('href');
      go.setAttribute('aria-disabled', 'true');
      hint.textContent = 'Fill in your team name and repository address.';
    }
  }
  for (const input of [team, repo, branch]) input.addEventListener('input', update);

  page.appendChild(
    h(
      'div',
      { class: 'card' },
      h('p', {}, 'Your bot lives in your own ', h('strong', {}, 'public GitHub repository'), ', with ', h('code', {}, 'bot.py'), ' at the top level. Register it here once; after that, pushing to the repository updates your bot.'),
      h('div', { class: 'form' },
        h('label', { for: 'reg-team' }, 'Team name'), team, teamMsg,
        h('label', { for: 'reg-repo' }, 'Repository address'), repo, repoMsg,
        h('label', { for: 'reg-branch' }, 'Branch (optional)'), branch, branchMsg,
        go, hint),
      h('h2', { style: 'margin-top:1.5rem' }, 'What happens next'),
      h('ol', {},
        h('li', {}, 'GitHub opens a registration form, already filled in. You need a GitHub account, and you must be signed in as ', h('strong', {}, 'the account that owns the repository'), ': registrations from anyone else are rejected, so nobody can register your repository for you.'),
        h('li', {}, 'Press “Submit new issue”. The arena checks it within a minute and replies on the issue.'),
        h('li', {}, 'The organiser approves it (they add an ', h('code', {}, 'approved'), ' label). Your bot is then fetched and starts playing. Watch its status on the ', h('a', { href: '#/submissions' }, 'Submissions'), ' page.'),
        h('li', {}, 'To change your repository, open a new registration for the same team from the same account. To withdraw, close the issue.')),
      h('p', { class: 'note' }, 'All registrations are public: ', h('a', { href: registryIssuesUrl(registry), target: '_blank', rel: 'noopener noreferrer' }, 'see them on GitHub'), '. New here? ', h('a', { href: '#/submit' }, 'Read how to write and test a bot'), '.'),
    ),
  );
  const waiting = registrationsCard(ctx.data.registrations || []);
  if (waiting) page.appendChild(waiting);
  update();
  return { el: page, title: 'Register' };
}
