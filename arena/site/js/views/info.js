// The Info page of the live format (#/info; #/submit opens it too): the
// values and commands needed to join, how this site works, then the
// organiser's guide. Everything from info.json is untrusted text.

import { loadGuide } from '../api.js';
import { h } from '../dom.js';
import { connectInfo, howItWorks, safeHref } from '../info-core.js';
import { renderMarkdown } from '../markdown.js';

/**
 * Copies `text` to the clipboard. Tries the clipboard API, then a hidden
 * textarea with execCommand; resolves false when neither worked (the caller
 * then selects the text so it can be copied by hand).
 */
export async function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the older way */
  }
  const area = h('textarea', { readonly: true, 'aria-hidden': 'true', tabindex: '-1', style: 'position:fixed;top:0;left:-9999px;opacity:0' });
  area.value = text;
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = Boolean(document.execCommand && document.execCommand('copy'));
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

/** A Copy button for `getText()`; it says Copied (or how to copy by hand) in a status line. */
function copyButton(getText, label, status, select = null) {
  const button = h('button', { type: 'button', class: 'copy', 'aria-label': `Copy ${label}` }, 'Copy');
  let reset = null;
  button.addEventListener('click', async () => {
    const ok = await copyText(getText());
    button.textContent = ok ? 'Copied' : 'Copy failed';
    status.textContent = ok ? `${label} copied.` : `Could not copy automatically. Select the ${label} and copy it by hand.`;
    if (!ok && select) select();
    clearTimeout(reset);
    reset = setTimeout(() => {
      button.textContent = 'Copy';
      status.textContent = '';
    }, 2500);
  });
  return button;
}

/** A read-only text box (selected on focus) with its Copy button. */
function copyBox(id, label, value, status) {
  const input = h('input', { id, type: 'text', readonly: true, class: 'copybox-input', 'aria-label': label, value, spellcheck: 'false', autocomplete: 'off' });
  input.value = value;
  input.addEventListener('focus', () => input.select());
  return h('div', { class: 'copybox' }, input, copyButton(() => input.value, label.toLowerCase(), status, () => input.select()));
}

/** A command in a code block, with its Copy button. */
function commandBlock(title, command, status) {
  return h(
    'div',
    { class: 'cmdbox' },
    h('div', { class: 'cmd-head' }, h('span', { class: 'small' }, title), copyButton(() => command, title.toLowerCase(), status)),
    h('pre', { class: 'cmd', tabindex: '0', 'aria-label': title }, h('code', {}, command)),
  );
}

function connectCard(info) {
  const connect = connectInfo(info);
  const status = h('p', { class: 'note copy-status', role: 'status' });
  const card = h('section', { class: 'card connect', 'aria-labelledby': 'connect-h' }, h('h2', { id: 'connect-h' }, 'Connect now'));

  card.appendChild(h('h3', { class: 'k' }, 'Server address'));
  card.appendChild(connect.hasServer ? copyBox('server-url', 'Server address', connect.server, status) : h('p', { class: 'missing' }, connect.serverLine));

  card.appendChild(h('h3', { class: 'k' }, 'Join code'));
  card.appendChild(connect.hasCode ? copyBox('join-code', 'Join code', connect.code, status) : h('p', { class: 'missing' }, connect.codeLine));

  const form = safeHref(info.form_url);
  if (info.form_url) {
    card.appendChild(h('h3', { class: 'k' }, 'Backup submission form'));
    card.appendChild(
      form
        ? h('p', {}, h('a', { href: form, target: '_blank', rel: 'noopener noreferrer' }, 'Open the backup submission form'), ' (opens in a new tab). Use it if the connection does not work.')
        : h('p', {}, info.form_url),
    );
  }

  card.appendChild(h('h3', { class: 'k' }, '1. Get your key'));
  card.appendChild(
    h(
      'p',
      { class: 'note' },
      `Choose a team name (lowercase letters, digits, “-” and “_”) and replace YOUR-TEAM-NAME${connect.hasCode ? '' : ' and YOUR-CODE'} below. The reply holds your api_key: save it, it cannot be looked up again.`,
    ),
  );
  card.appendChild(commandBlock('Register (macOS, Linux, Windows with curl)', connect.commands.register.bash, status));
  card.appendChild(commandBlock('Register (Windows PowerShell)', connect.commands.register.powershell, status));

  card.appendChild(h('h3', { class: 'k' }, '2. Run your bot'));
  card.appendChild(h('p', { class: 'note' }, 'Leave it running. Only bots connected when the tournament starts get a seat.'));
  card.appendChild(commandBlock('Run your bot', connect.commands.run, status));
  card.appendChild(status);
  return card;
}

function worksCard(info, manifest) {
  return h(
    'section',
    { class: 'card works', 'aria-labelledby': 'works-h' },
    h('h2', { id: 'works-h' }, 'How this site works'),
    howItWorks(info, manifest).map((paragraph) => h('p', {}, paragraph)),
  );
}

/** The Info page. */
export async function infoView(ctx) {
  const info = ctx.data.info;
  const manifest = ctx.data.manifest;
  const page = h('div', { class: 'page guide info' }, h('header', {}, h('h1', {}, 'Info')));
  if (info.note) page.appendChild(h('p', { class: 'card info-note' }, info.note));
  page.append(connectCard(info), worksCard(info, manifest));
  if (manifest.has_guide) {
    try {
      page.appendChild(renderMarkdown(await loadGuide()));
    } catch {
      page.appendChild(h('div', { class: 'empty card' }, 'The guide could not be loaded. This page tries again every few seconds.'));
    }
  }
  return { el: page, title: 'Info' };
}
