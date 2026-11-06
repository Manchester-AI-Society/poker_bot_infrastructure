// The Home page of the live format: what the event is, when things happen,
// the prize, the rules and who to ask. The text comes from event.json (through
// info.json) and is untrusted: it is only ever shown as text.

import { h } from '../dom.js';

const FALLBACK_INTRO = [
  'Teams write a Python poker bot. Each bot connects over the internet to the organiser\'s server and plays a no-limit Texas Hold\'em knockout against everyone else\'s bots.',
];

/** The Home page. */
export function homeView(ctx) {
  const event = ctx.data.info && ctx.data.info.event;
  const intro = event && event.intro.length ? event.intro : FALLBACK_INTRO;
  const page = h('div', { class: 'page home' });

  page.appendChild(
    h(
      'header',
      {},
      h('h1', {}, 'Welcome'),
      event && event.tagline ? h('span', { class: 'muted' }, event.tagline) : null,
    ),
  );

  page.appendChild(
    h(
      'p',
      { class: 'home-cta' },
      h('a', { class: 'button', href: '#/info' }, 'How to join'),
      h('a', { class: 'button', href: '#/live' }, 'Watch live'),
      h('a', { class: 'button', href: '#/teams' }, 'Teams'),
    ),
  );

  page.appendChild(
    h('section', { class: 'card', 'aria-labelledby': 'challenge-h' }, h('h2', { id: 'challenge-h' }, 'The challenge'), intro.map((paragraph) => h('p', { class: 'home-text' }, paragraph))),
  );

  if (event && event.prize) {
    page.appendChild(h('section', { class: 'card prize', 'aria-labelledby': 'prize-h' }, h('h2', { id: 'prize-h' }, 'Prize'), h('p', { class: 'home-prize' }, event.prize)));
  }

  if (event && event.timeline.length) {
    page.appendChild(
      h(
        'section',
        { class: 'card', 'aria-labelledby': 'timeline-h' },
        h('h2', { id: 'timeline-h' }, 'Timeline'),
        h(
          'ol',
          { class: 'timeline' },
          event.timeline.map((row) =>
            h(
              'li',
              {},
              h('span', { class: 'when' }, row.time),
              h('div', {}, h('strong', {}, row.title), row.detail ? h('p', { class: 'home-text' }, row.detail) : null),
            ),
          ),
        ),
      ),
    );
  }

  if (event && event.rules.length) {
    page.appendChild(
      h('section', { class: 'card', 'aria-labelledby': 'rules-h' }, h('h2', { id: 'rules-h' }, 'The rules'), h('ul', { class: 'home-list' }, event.rules.map((rule) => h('li', {}, rule)))),
    );
  }

  if (event && event.contact) {
    page.appendChild(h('section', { class: 'card', 'aria-labelledby': 'help-h' }, h('h2', { id: 'help-h' }, 'Help'), h('p', { class: 'home-text' }, event.contact)));
  }

  return { el: page, title: 'Home' };
}
