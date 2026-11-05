import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  inlineText,
  isSafeLink,
  parseInline,
  parseMarkdown,
} from '../../arena/site/js/markdown.js';

const guide = readFileSync(new URL('../../SUBMITTING.md', import.meta.url), 'utf8');

test('inline code, bold and links are recognised and nothing is lost', () => {
  const pieces = parseInline('Run `python -m arena` **now** and see [the docs](https://x.io/a_b).');

  assert.deepEqual(
    pieces.map((p) => p.t),
    ['text', 'code', 'text', 'strong', 'text', 'link', 'text'],
  );
  assert.equal(pieces[1].v, 'python -m arena');
  assert.equal(pieces[5].href, 'https://x.io/a_b');
  assert.equal(inlineText(pieces), 'Run python -m arena now and see the docs.');
});

test('underscores and single stars in plain text are left alone', () => {
  assert.equal(inlineText(parseInline('team_name and a*b and snake_case')), 'team_name and a*b and snake_case');
});

test('only plain http and https links are treated as safe', () => {
  assert.equal(isSafeLink('https://github.com/a/b'), true);
  assert.equal(isSafeLink('http://example.com'), true);
  assert.equal(isSafeLink('javascript:alert(1)'), false);
  assert.equal(isSafeLink('data:text/html,<b>x</b>'), false);
  assert.equal(isSafeLink('bots/README.md'), false);
  assert.equal(isSafeLink('//evil.example/x'), false);
  assert.equal(isSafeLink('https://a b'), false);
});

test('headings, paragraphs and wrapped lines', () => {
  const blocks = parseMarkdown('# Title\n\nfirst line\nsecond line\n\n## Next\n');

  assert.deepEqual(
    blocks.map((b) => b.type),
    ['heading', 'paragraph', 'heading'],
  );
  assert.equal(blocks[0].level, 1);
  assert.equal(inlineText(blocks[1].inline), 'first line second line');
});

test('bullet and numbered lists, including wrapped items', () => {
  const blocks = parseMarkdown(
    ['* one', '* two', '  continues here', '', '1. first', '2. second', '   wrapped'].join('\n'),
  );

  assert.deepEqual(
    blocks.map((b) => [b.type, b.ordered, b.items.length]),
    [
      ['list', false, 2],
      ['list', true, 2],
    ],
  );
  assert.equal(inlineText(blocks[0].items[1]), 'two continues here');
  assert.equal(inlineText(blocks[1].items[1]), 'second wrapped');
});

test('fenced code keeps its lines exactly, including blank lines and symbols', () => {
  const blocks = parseMarkdown(['```bash', 'a | b', '', '  indented **not bold**', '```'].join('\n'));

  assert.deepEqual(blocks, [
    { type: 'code', lang: 'bash', text: 'a | b\n\n  indented **not bold**' },
  ]);
});

test('an unclosed code fence takes the rest of the file instead of crashing', () => {
  const blocks = parseMarkdown('```\nnever closed\nstill code');

  assert.equal(blocks[0].type, 'code');
  assert.equal(blocks[0].text, 'never closed\nstill code');
});

test('tables, including an empty header row and escaped pipes', () => {
  const blocks = parseMarkdown(['| | |', '|---|---|', '| **Time** | 1 second |', '| a \\| b | `x` |'].join('\n'));

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].type, 'table');
  assert.equal(blocks[0].rows.length, 2);
  assert.equal(inlineText(blocks[0].rows[0][0]), 'Time');
  assert.equal(inlineText(blocks[0].rows[1][0]), 'a | b');
  assert.equal(inlineText(blocks[0].header[0]).trim(), '');
});

test('a block quote and Windows line endings', () => {
  const blocks = parseMarkdown('> a quoted\r\n> note\r\n\r\nafter\r\n');

  assert.deepEqual(blocks.map((b) => b.type), ['quote', 'paragraph']);
  assert.equal(inlineText(blocks[0].inline), 'a quoted note');
});

test('script-like text is just text, never markup', () => {
  const blocks = parseMarkdown('<script>alert(1)</script> and <img src=x onerror=alert(1)>');

  assert.equal(blocks[0].type, 'paragraph');
  assert.equal(inlineText(blocks[0].inline), '<script>alert(1)</script> and <img src=x onerror=alert(1)>');
});

// ---- the real guide ------------------------------------------------------

function textOfEverything(blocks) {
  const out = [];
  for (const b of blocks) {
    if (b.inline) out.push(inlineText(b.inline));
    if (b.items) b.items.forEach((item) => out.push(inlineText(item)));
    if (b.header) b.header.forEach((c) => out.push(inlineText(c)));
    if (b.rows) b.rows.forEach((row) => row.forEach((c) => out.push(inlineText(c))));
  }
  return out.join('\n');
}

test('SUBMITTING.md is read into the structure it was written with', () => {
  const blocks = parseMarkdown(guide);
  const count = (type) => blocks.filter((b) => b.type === type).length;

  assert.equal(blocks[0].type, 'heading');
  assert.equal(inlineText(blocks[0].inline), 'How to submit your bot');
  assert.ok(count('heading') >= 8, 'a heading per step');
  assert.ok(count('code') >= 4, 'the command blocks');
  assert.equal(count('table'), 3, 'what the bot is given, the problems table, the rules table');
  assert.ok(count('list') >= 3);
});

test('no markdown syntax is left showing in the rendered text of SUBMITTING.md', () => {
  const text = textOfEverything(parseMarkdown(guide));

  assert.ok(!text.includes('**'), 'a bold marker was not rendered');
  assert.ok(!text.includes('```'), 'a code fence leaked into the text');
  assert.ok(!/\]\(/.test(text), 'a link was not rendered');
  assert.ok(!/^\s*\|?\s*-{3,}/m.test(text), 'a table rule leaked');
  assert.ok(!/^#{1,4}\s/m.test(text), 'a heading marker leaked');
  assert.ok(!/(^|\n)\s*[*-]\s/.test(text), 'a bullet marker leaked');
});

test('every command in the guide survives as code, character for character', () => {
  const code = parseMarkdown(guide)
    .filter((b) => b.type === 'code')
    .map((b) => b.text)
    .join('\n');

  assert.match(code, /python -m arena validate bots\/myteam/);
  assert.match(code, /python -m arena match bots\/myteam call --deals 200/);
  assert.match(code, /pip install -r requirements\.txt/);
  assert.match(code, /bot\.py {10}<- required, at the top level/);
});

test('the relative link to bots/README.md is plain text on the site, not a broken link', () => {
  const links = [];
  const walk = (pieces) =>
    pieces.forEach((p) => {
      if (p.t === 'link') links.push(p.href);
      if (p.children) walk(p.children);
    });
  for (const b of parseMarkdown(guide)) {
    [b.inline, ...(b.items || [])].filter(Boolean).forEach(walk);
  }

  assert.ok(links.length > 0);
  assert.ok(links.some((href) => !isSafeLink(href)), 'the guide links to a repo file');
});
