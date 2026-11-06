import { loadGuide } from '../api.js';
import { h } from '../dom.js';
import { renderMarkdown } from '../markdown.js';
import { isTournament } from '../tournament-core.js';

/** The how-to-submit guide (SUBMITTING.md), shown as a page. */
export async function guideView(ctx) {
  const page = h('div', { class: 'page guide' });
  if (!ctx.data.manifest.has_guide) {
    page.appendChild(h('header', {}, h('h1', {}, 'How to submit')));
    page.appendChild(
      h('div', { class: 'empty card' }, 'The organiser has not published a submission guide.'),
    );
    return { el: page, title: 'How to submit' };
  }
  let text;
  try {
    text = await loadGuide();
  } catch (error) {
    page.appendChild(h('div', { class: 'empty card' }, 'The guide could not be loaded. This page tries again every few seconds.'));
    return { el: page, title: 'How to submit' };
  }
  page.appendChild(renderMarkdown(text));
  if (!isTournament(ctx.data.manifest)) {
    // The tournament has no repository submissions to check on.
    page.appendChild(
      h(
        'p',
        { class: 'note' },
        'Already submitted? ',
        h('a', { href: '#/submissions' }, 'Check the status of your bot'),
        '.',
      ),
    );
  }
  return { el: page, title: 'How to submit' };
}
