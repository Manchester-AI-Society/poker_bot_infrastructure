import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildIssueUrl,
  checkForm,
  registryIssuesUrl,
  validateBranch,
  validateRepo,
  validateTeam,
} from '../../arena/site/js/register-core.js';

test('team names: capitals are fixed, bad characters refused', () => {
  assert.deepEqual(validateTeam('  Team-Fox ').value, 'team-fox');
  assert.ok(validateTeam('Team-Fox').ok);
  for (const name of ['', '   ', '-fox', 'a b', 'fox!', 'x'.repeat(33), 'a/b', '../x']) {
    assert.equal(validateTeam(name).ok, false, JSON.stringify(name));
  }
  assert.ok(validateTeam('x'.repeat(32)).ok);
});

test('repository: public https GitHub addresses only', () => {
  const good = validateRepo('https://github.com/b1-ing/poker-arena-test-fox');
  assert.ok(good.ok);
  assert.equal(good.owner, 'b1-ing');
  assert.equal(good.name, 'poker-arena-test-fox');
  assert.equal(validateRepo('https://github.com/b1-ing/fox.git/').name, 'fox');
  for (const url of [
    '',
    'http://github.com/a/b',
    'git@github.com:a/b.git',
    'https://gitlab.com/a/b',
    'https://github.com/a',
    'https://github.com/a/b/tree/main',
    'https://evil.example/github.com/a/b',
    'https://github.com.evil.example/a/b',
    'file:///etc/passwd',
  ]) {
    assert.equal(validateRepo(url).ok, false, url);
  }
});

test('a token in the address is called out, not echoed back', () => {
  const r = validateRepo('https://ghp_secret@github.com/a/b');
  assert.equal(r.ok, false);
  assert.match(r.message, /token|password/);
  assert.ok(!r.message.includes('ghp_secret'));
});

test('branch is optional but must be sane', () => {
  assert.ok(validateBranch('').ok);
  assert.ok(validateBranch('main').ok);
  assert.ok(validateBranch('feature/x-1.2').ok);
  for (const b of ['-rf', '--upload-pack=x', 'a b', 'a;b', '..']) {
    assert.equal(validateBranch(b).ok, false, b);
  }
});

test('the issue link is pre-filled and encoded', () => {
  const url = new URL(
    buildIssueUrl('org/registry', {
      team: 'fox',
      repo: 'https://github.com/a/b',
      branch: 'dev & more',
    }),
  );
  assert.equal(url.origin + url.pathname, 'https://github.com/org/registry/issues/new');
  assert.equal(url.searchParams.get('template'), 'register.yml');
  assert.equal(url.searchParams.get('team'), 'fox');
  assert.equal(url.searchParams.get('repo'), 'https://github.com/a/b');
  assert.equal(url.searchParams.get('branch'), 'dev & more');
  assert.equal(url.searchParams.get('title'), 'Register: fox');
});

test('no branch means no branch parameter', () => {
  const url = new URL(buildIssueUrl('o/r', { team: 't', repo: 'https://github.com/a/b', branch: '' }));
  assert.equal(url.searchParams.has('branch'), false);
});

test('the form is ready only when all three parts are fine', () => {
  const base = { team: 'fox', repo: 'https://github.com/a/b', branch: '' };
  assert.ok(checkForm(base).ready);
  assert.equal(checkForm({ ...base, team: '' }).ready, false);
  assert.equal(checkForm({ ...base, repo: 'nope' }).ready, false);
  assert.equal(checkForm({ ...base, branch: '-x' }).ready, false);
});

test('issues list link', () => {
  assert.equal(registryIssuesUrl('o/r'), 'https://github.com/o/r/issues');
});
