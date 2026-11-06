// App shell: hash router, header controls, and the polling loop that keeps
// the data fresh. Light and dark follow the OS (CSS only); there is no switch.
// There is no framework; each view returns an element (or
// {el, title, dispose}) and the shell swaps it into <main>.

import { data, refresh } from './api.js';
import { h } from './dom.js';
import { parseHash } from './format.js';
import { isTournament, registerFormOpen, updatedText } from './tournament-core.js';
import { guideView } from './views/guide.js';
import { homeView } from './views/home.js';
import { leaderboardView } from './views/leaderboard.js';
import { matchesView } from './views/matches.js';
import { matrixView } from './views/matrix.js';
import { registerView } from './views/register.js';
import { replayView } from './views/replay.js';
import { submissionsView } from './views/submissions.js';
import { teamView } from './views/team.js';
import { tournamentView } from './views/tournament.js';
import { tvView } from './views/tv.js';

const POLL_SECONDS = 10;
const STALE_SECONDS = 45;

const main = document.getElementById('main');
const updated = document.getElementById('updated');
const kindSwitch = document.getElementById('kind-switch');

let kind = 'final';
let current = null; // the view now on screen
let renderToken = 0;

// ---- small persisted preferences ------------------------------------

function remember(key, value) {
  try {
    if (value == null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch { /* storage may be blocked; the page works without it */ }
}

function recall(key) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

// ---- routes -----------------------------------------------------------

// `live` routes are redrawn when new data arrives; the others (a replay being
// watched, the TV rotation) keep running and read fresh data when they need it.
const ROUTES = {
  // The home page is the leaderboard, or the tournament in that format.
  '': { view: homePage, live: true },
  tournament: { view: tournamentView, live: true },
  matrix: { view: matrixView, live: true },
  matches: { view: matchesView, live: true },
  team: { view: teamView, live: true },
  submissions: { view: submissionsView, live: true },
  submit: { view: guideView, live: true },
  register: { view: registerView, live: true },
  replay: { view: replayView, live: false },
  tv: { view: tvView, live: false },
};

// The home page: the event's Home (when the organiser gave event.json), else
// the tournament, or the leaderboard in the ladder format.
function homePage(ctx) {
  if (!isTournament(ctx.data.manifest)) return leaderboardView(ctx);
  return ctx.data.event ? homeView(ctx) : tournamentView(ctx);
}

// Pages that exist only for the repository-submission format. In a tournament
// the Register page (a team-name form) exists only when the organiser set one up.
const LADDER_ONLY = new Set(['register', 'submissions']);

function hiddenRoute(name) {
  if (!isTournament(data.manifest)) return false;
  if (name === 'register') return !registerFormOpen(data.manifest);
  return LADDER_ONLY.has(name);
}

function chooseKind(requested) {
  if (isTournament(data.manifest)) return 'tournament'; // no Final/Ladder choice
  const available = (data.manifest && data.manifest.kinds) || ['ladder'];
  const preferred = requested || recall('arena-kind');
  if (preferred && available.includes(preferred)) return preferred;
  return available.includes('final') ? 'final' : 'ladder';
}

function showNoData() {
  // Show the real reason when loading failed (a missing export, a broken
  // connection), so an organiser can tell them apart; otherwise just loading.
  const text = data.error
    ? `The results could not be loaded (${data.error.message}). This page tries again every few seconds.`
    : 'Loading results…';
  main.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'empty card' }, text)));
}

async function render({ keepScroll = false } = {}) {
  // A hash change can arrive before the first load finishes; views need data.
  if (!data.manifest) {
    showNoData();
    return;
  }
  const token = ++renderToken;
  let { path, query } = parseHash(location.hash);
  if (hiddenRoute(path[0])) {
    // No repository submissions here, and no register page without a form.
    history.replaceState(null, '', '#/');
    ({ path, query } = parseHash(location.hash));
  }
  const route = ROUTES[path[0] || ''] || ROUTES[''];
  if (query.kind) remember('arena-kind', query.kind);
  kind = chooseKind(query.kind);

  const scrollY = keepScroll ? window.scrollY : 0;
  const ctx = { data, kind, path, query };
  let result;
  try {
    result = await route.view(ctx);
  } catch (error) {
    console.error(error);
    result = {
      el: h('div', { class: 'page' }, h('div', { class: 'empty card' }, 'Something went wrong showing this page. ', h('a', { href: '#/' }, 'Back to the leaderboard'))),
      title: 'Error',
    };
  }
  if (token !== renderToken) {
    if (result && result.dispose) result.dispose(); // a newer navigation won
    return;
  }
  const view = result instanceof Node ? { el: result } : result;
  if (current && current.dispose) current.dispose();
  current = view;
  current.live = route.live;
  // A redraw for fresh data must not take the cursor out of a field being typed in.
  const active = keepScroll && document.activeElement;
  const focusId = active && active.id && main.contains(active) ? active.id : null;
  const caret = focusId && active.selectionStart != null ? [active.selectionStart, active.selectionEnd] : null;
  main.replaceChildren(view.el);
  const refocus = focusId && document.getElementById(focusId);
  if (refocus) {
    refocus.focus({ preventScroll: true });
    if (caret && refocus.setSelectionRange) refocus.setSelectionRange(caret[0], caret[1]);
  }
  document.title = `${view.title ? view.title + ' · ' : ''}${data.manifest ? data.manifest.title : 'Poker Bot Competition'}`;

  for (const link of document.querySelectorAll('.tabs a')) {
    const active = link.dataset.route === (path[0] || '');
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  paintKindSwitch();
  paintNav();
  if (keepScroll) window.scrollTo(0, scrollY);
  else {
    window.scrollTo(0, 0);
    if (path[0] !== 'tv') main.focus({ preventScroll: true });
  }
}

// ---- header controls --------------------------------------------------

function paintNav() {
  const tournament = isTournament(data.manifest);
  // The Register tab: in a tournament when the organiser set up the team-name
  // form, in the ladder format when there is a registry.
  const register = document.getElementById('nav-register');
  if (register) {
    register.hidden = tournament
      ? !registerFormOpen(data.manifest)
      : !(data.manifest && data.manifest.registry_repo);
  }
  // A tournament has no repository submissions.
  const submissions = document.getElementById('nav-submissions');
  if (submissions) submissions.hidden = tournament;
  // With a Home page the Tournament gets its own tab.
  const hasHome = tournament && Boolean(data.event);
  const tab = document.getElementById('nav-tournament');
  if (tab) tab.hidden = !hasHome;
  const home = document.getElementById('nav-home');
  if (home) home.textContent = hasHome ? 'Home' : tournament ? 'Tournament' : 'Leaderboard';
}

function paintKindSwitch() {
  const kinds = (data.manifest && data.manifest.kinds) || [];
  // The Final/Ladder switch is for the ladder format; a tournament shows both rounds at once.
  kindSwitch.hidden = isTournament(data.manifest) || kinds.length < 2;
  for (const button of kindSwitch.querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(button.dataset.kind === kind));
  }
}

kindSwitch.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  remember('arena-kind', button.dataset.kind);
  const { path, query } = parseHash(location.hash);
  if (query.kind) {
    // An explicit ?kind= in the address would override the click.
    delete query.kind;
    const rest = new URLSearchParams(query).toString();
    history.replaceState(null, '', '#/' + path.join('/') + (rest ? `?${rest}` : ''));
  }
  render();
});

function paintUpdated() {
  if (!data.manifest) {
    updated.textContent = '';
    return;
  }
  const age = (Date.now() - data.lastOk) / 1000;
  const since = Date.now() / 1000 - data.manifest.generated_at;
  const stale = Boolean(data.error) && age > STALE_SECONDS;
  updated.classList.toggle('stale', stale);
  updated.textContent = updatedText(data.manifest, since, { stale });
}

// ---- start ------------------------------------------------------------

async function poll() {
  const changed = await refresh();
  if (changed) {
    document.getElementById('brand').textContent = data.manifest.title;
    if (current && current.live) render({ keepScroll: true });
    else if (!current) render();
  } else if (!current && data.manifest) {
    render();
  }
  paintUpdated();
}

async function start() {
  await refresh();
  if (!data.manifest) {
    showNoData();
  } else {
    document.getElementById('brand').textContent = data.manifest.title;
    await render();
  }
  paintUpdated();
  setInterval(poll, POLL_SECONDS * 1000);
  setInterval(paintUpdated, 1000);
}

window.addEventListener('hashchange', () => render());
start();
