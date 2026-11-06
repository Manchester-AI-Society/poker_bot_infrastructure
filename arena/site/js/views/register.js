// The Register page. In the tournament format it registers a team NAME (a
// short Google Form the organiser runs); in the ladder format it opens the
// registry's GitHub issue form (register-ladder.js, unchanged).

import { h } from '../dom.js';
import { MAX_NAME_LENGTH, registerState } from '../register-name-core.js';
import { isTournament, registerFormOpen } from '../tournament-core.js';
import { ladderRegisterView } from './register-ladder.js';
import { STATUS_LEGEND, rosterList } from './roster.js';

// What was typed survives a redraw (the page redraws when new data arrives).
let draft = '';

function listedCard(teams) {
  const card = h('section', { class: 'card', 'aria-label': 'Names already listed' });
  card.appendChild(h('h2', { class: 'counted' }, 'Names already listed', h('span', { class: 'muted small' }, String(teams.length))));
  if (!teams.length) {
    card.appendChild(h('p', { class: 'note' }, 'No names are listed yet. Yours can be the first.'));
    return card;
  }
  card.appendChild(rosterList(teams, 'Names already listed'));
  card.appendChild(h('p', { class: 'note' }, STATUS_LEGEND));
  return card;
}

/** Tournament: pick a name, then continue to the organiser's registration form. */
function tournamentRegisterView(ctx) {
  const form = registerFormOpen(ctx.data.manifest);
  const teams = ctx.data.teams;
  const page = h('div', { class: 'page' });
  page.appendChild(h('header', {}, h('h1', {}, 'Register your team name')));

  const input = h('input', {
    id: 'team-name',
    type: 'text',
    name: 'team',
    autocomplete: 'off',
    autocapitalize: 'none',
    spellcheck: 'false',
    'aria-describedby': 'team-name-help team-name-msg',
  });
  input.value = draft;
  const message = h('p', { id: 'team-name-msg', class: 'field-msg', role: 'status' });
  const link = h('a', { class: 'btn-primary', role: 'link', 'aria-disabled': 'true' }, 'Continue to the registration form');

  function update() {
    const raw = input.value;
    const lowered = raw.toLowerCase();
    if (lowered !== raw) {
      // Typed capitals are lowercased for you, keeping the cursor where it was.
      const at = input.selectionStart;
      input.value = lowered;
      if (at != null) input.setSelectionRange(at, at);
    }
    draft = input.value;
    const state = registerState(form, teams, input.value);
    const bad = state.check.state === 'invalid' || Boolean(state.listed);
    const good = Boolean(state.link);
    message.textContent = '';
    if (state.message) {
      message.appendChild(h('span', { 'aria-hidden': 'true' }, bad ? '✗ ' : good ? '✓ ' : ''));
      message.appendChild(document.createTextNode(state.message));
    }
    message.classList.toggle('bad', bad);
    if (bad) input.setAttribute('aria-invalid', 'true');
    else input.removeAttribute('aria-invalid');
    if (state.link) {
      link.setAttribute('href', state.link);
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
      link.removeAttribute('aria-disabled');
    } else {
      link.removeAttribute('href');
      link.removeAttribute('target');
      link.removeAttribute('rel');
      link.setAttribute('aria-disabled', 'true');
    }
  }
  input.addEventListener('input', update);

  const intro = h(
    'div',
    { class: 'card' },
    h('p', { id: 'team-name-help' }, 'Register the name of your team and it is listed on this site right away. ', h('strong', {}, 'This does not submit a bot.'), ' Bots are uploaded through the submission form: see ', h('a', { href: '#/submit' }, 'How to submit'), '. The name turns to “submitted” in the list below when a bot with exactly that name arrives.'),
  );
  if (!form) {
    intro.appendChild(h('p', {}, 'Registration is not open for this event.'));
    page.appendChild(intro);
    return { el: page, title: 'Register' };
  }
  const fields = h(
    'form',
    { class: 'card field', novalidate: true },
    h('label', { for: 'team-name' }, 'Team name'),
    input,
    h('p', { class: 'note' }, `Lowercase letters, digits, “-” and “_”; up to ${MAX_NAME_LENGTH} characters; start with a letter or a digit. Capitals are turned into lowercase for you.`),
    message,
    link,
    h('p', { class: 'note' }, 'The button opens the organiser’s registration form in a new tab with the name filled in. Send that form to finish. A name that is already listed cannot be registered again.'),
  );
  fields.addEventListener('submit', (event) => {
    event.preventDefault();
    if (link.getAttribute('href')) link.click();
  });
  page.append(intro, fields, listedCard(teams));
  update();
  return { el: page, title: 'Register' };
}

export function registerView(ctx) {
  return isTournament(ctx.data.manifest) ? tournamentRegisterView(ctx) : ladderRegisterView(ctx);
}

