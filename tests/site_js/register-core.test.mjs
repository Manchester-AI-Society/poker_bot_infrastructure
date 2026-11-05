import test from 'node:test';
import assert from 'node:assert/strict';
import { registerUrl, registryIssuesUrl } from '../../arena/site/js/register-core.js';

test('the register link opens the registry form', () => {
  assert.equal(
    registerUrl('org/registry'),
    'https://github.com/org/registry/issues/new?template=register.yml',
  );
});

test('the issues link', () => {
  assert.equal(registryIssuesUrl('o/r'), 'https://github.com/o/r/issues');
});

test('anything that is not OWNER/REPO gives no link', () => {
  for (const bad of ['', null, undefined, 'norepo', 'a/b/c', 'a b/c', 'https://evil.example/x', '../x/y', 'a/b?x=1']) {
    assert.equal(registerUrl(bad), null, String(bad));
    assert.equal(registryIssuesUrl(bad), null, String(bad));
  }
});
