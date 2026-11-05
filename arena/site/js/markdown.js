// A small markdown reader for the how-to-submit guide. It understands only
// what that guide uses: headings, paragraphs, bullet and numbered lists,
// fenced code, tables, quotes, and inline code, bold and links.
//
// parseMarkdown/parseInline are pure (tested in Node). renderMarkdown builds
// elements with textContent only, so nothing in the text can become markup,
// and only http(s) links are made clickable.

import { h } from './dom.js';

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))/g;
const FENCE = /^\s*```\s*([\w-]*)\s*$/;
const HEADING = /^(#{1,4})\s+(.*?)\s*#*\s*$/;
const LIST_ITEM = /^([*-]|\d+\.)\s+(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

/** Splits a line of text into plain, code, bold and link pieces. */
export function parseInline(text) {
  const out = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) out.push({ t: 'text', v: text.slice(last, match.index) });
    const [whole] = match;
    if (match[1]) {
      out.push({ t: 'code', v: whole.slice(1, -1) });
    } else if (match[2]) {
      out.push({ t: 'strong', children: parseInline(whole.slice(2, -2)) });
    } else {
      const split = whole.indexOf('](');
      out.push({
        t: 'link',
        href: whole.slice(split + 2, -1),
        children: parseInline(whole.slice(1, split)),
      });
    }
    last = match.index + whole.length;
  }
  if (last < text.length) out.push({ t: 'text', v: text.slice(last) });
  return out;
}

function splitRow(line) {
  let row = line.trim();
  if (row.startsWith('|')) row = row.slice(1);
  if (row.endsWith('|') && !row.endsWith('\\|')) row = row.slice(0, -1);
  return row.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, '|'));
}

const isBlank = (line) => line.trim() === '';

function startsBlock(line, next) {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    /^>/.test(line) ||
    LIST_ITEM.test(line) ||
    (line.trim().startsWith('|') && next !== undefined && TABLE_RULE.test(next))
  );
}

/** Reads markdown into blocks: heading, paragraph, list, code, table, quote. */
export function parseMarkdown(source) {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (isBlank(line)) {
      i += 1;
      continue;
    }
    const fence = line.match(FENCE);
    if (fence) {
      const code = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // the closing fence
      blocks.push({ type: 'code', lang: fence[1], text: code.join('\n') });
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, inline: parseInline(heading[2]) });
      i += 1;
      continue;
    }
    if (line.trim().startsWith('|') && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
      const header = splitRow(line).map(parseInline);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitRow(lines[i]).map(parseInline));
        i += 1;
      }
      blocks.push({ type: 'table', header, rows });
      continue;
    }
    if (/^>/.test(line)) {
      const quoted = [];
      while (i < lines.length && /^>/.test(lines[i])) {
        quoted.push(lines[i].replace(/^>\s?/, ''));
        i += 1;
      }
      blocks.push({ type: 'quote', inline: parseInline(quoted.join(' ').trim()) });
      continue;
    }
    const item = line.match(LIST_ITEM);
    if (item) {
      const ordered = /\d/.test(item[1]);
      const items = [];
      while (i < lines.length) {
        const entry = lines[i].match(LIST_ITEM);
        if (!entry || /\d/.test(entry[1]) !== ordered) break;
        let text = entry[2];
        i += 1;
        // Wrapped lines of the same item are indented.
        while (i < lines.length && /^\s+\S/.test(lines[i]) && !LIST_ITEM.test(lines[i])) {
          text += ' ' + lines[i].trim();
          i += 1;
        }
        items.push(parseInline(text));
        while (i < lines.length && isBlank(lines[i]) && LIST_ITEM.test(lines[i + 1] || '')) i += 1;
      }
      blocks.push({ type: 'list', ordered, items });
      continue;
    }
    const paragraph = [];
    while (i < lines.length && !isBlank(lines[i]) && !(paragraph.length && startsBlock(lines[i], lines[i + 1]))) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    blocks.push({ type: 'paragraph', inline: parseInline(paragraph.join(' ')) });
  }
  return blocks;
}

/** Plain text of inline pieces (used by tests, and for the page title). */
export function inlineText(pieces) {
  return pieces
    .map((p) => (p.children ? inlineText(p.children) : p.v))
    .join('');
}

export function isSafeLink(href) {
  return /^https?:\/\/[^\s]+$/i.test(href);
}

function inlineNodes(pieces) {
  return pieces.map((piece) => {
    if (piece.t === 'code') return h('code', {}, piece.v);
    if (piece.t === 'strong') return h('strong', {}, inlineNodes(piece.children));
    if (piece.t === 'link') {
      // Only web links are clickable; a relative link (to a file that is not on
      // this site) is shown as plain text.
      if (!isSafeLink(piece.href)) return h('span', {}, inlineNodes(piece.children));
      return h(
        'a',
        { href: piece.href, target: '_blank', rel: 'noopener noreferrer' },
        inlineNodes(piece.children),
      );
    }
    return piece.v;
  });
}

/** Builds a container element for the parsed blocks. */
export function renderMarkdown(source) {
  const root = h('div', { class: 'md' });
  for (const block of parseMarkdown(source)) {
    switch (block.type) {
      case 'heading':
        root.appendChild(h(`h${Math.min(block.level + 1, 6)}`, {}, inlineNodes(block.inline)));
        break;
      case 'paragraph':
        root.appendChild(h('p', {}, inlineNodes(block.inline)));
        break;
      case 'quote':
        root.appendChild(h('blockquote', {}, inlineNodes(block.inline)));
        break;
      case 'code':
        root.appendChild(
          h('pre', { tabindex: '0' }, h('code', { class: block.lang ? `lang-${block.lang}` : null }, block.text)),
        );
        break;
      case 'list':
        root.appendChild(
          h(block.ordered ? 'ol' : 'ul', {}, block.items.map((item) => h('li', {}, inlineNodes(item)))),
        );
        break;
      case 'table': {
        const head = block.header.some((cell) => inlineText(cell).trim());
        root.appendChild(
          h(
            'div',
            { class: 'tablewrap' },
            h(
              'table',
              // A table with no header row is a list of labelled facts: keep
              // its short labels on one line. Real tables wrap normally.
              { class: head ? 'tbl' : 'tbl labels' },
              head
                ? h('thead', {}, h('tr', {}, block.header.map((cell) => h('th', { scope: 'col' }, inlineNodes(cell)))))
                : null,
              h(
                'tbody',
                {},
                block.rows.map((row) => h('tr', {}, row.map((cell) => h('td', {}, inlineNodes(cell))))),
              ),
            ),
          ),
        );
        break;
      }
      default:
        break;
    }
  }
  return root;
}
