import test from 'node:test';
import assert from 'node:assert/strict';
import {
  checkName,
  formAddress,
  foldName,
  isValidName,
  listedTeam,
  registerLink,
  registerState,
} from '../../arena/site/js/register-name-core.js';

// The shape the exporter validates: a Google Form's prefilled link ending in the entry.
const FORM = 'https://docs.google.com/forms/d/e/1FAIpQLSdEXAMPLE_id-1/viewform?usp=pp_url&entry.123456789=';

const TEAMS = [
  { team: 'alpha', status: 'submitted' },
  { team: 'bravo', status: 'registered' },
  { team: 'old-export' }, // an export from before the field existed
];

test('valid names', () => {
  for (const name of ['a', '7', 'team-1', 'my_bot', 'a-b_c', '0xdeadbeef', 'a'.repeat(32)]) {
    const checked = checkName(name);
    assert.equal(checked.state, 'valid', name);
    assert.equal(checked.name, name);
    assert.equal(checked.message, '', name);
    assert.ok(isValidName(name), name);
  }
});

test('invalid names say why, in words', () => {
  const cases = {
    'has space': /space/,
    'a.b': /“\.”/,
    'x!y?': /“!”, “\?”/,
    'é': /“é”/,
    'a/b': /“\/”/,
    'a&entry.1=evil': /“&”/,
    '-leading': /start with a letter or a digit/,
    _x: /start with a letter or a digit/,
  };
  for (const [name, pattern] of Object.entries(cases)) {
    const checked = checkName(name);
    assert.equal(checked.state, 'invalid', name);
    assert.match(checked.message, pattern, name);
    assert.ok(!isValidName(name), name);
  }
});

test('32 characters is the longest name; 33 is refused with the count', () => {
  assert.equal(checkName('b'.repeat(32)).state, 'valid');
  const long = checkName('b'.repeat(33));
  assert.equal(long.state, 'invalid');
  assert.match(long.message, /33 characters/);
  assert.match(long.message, /at most 32/);
});

test('nothing typed says nothing; spaces around a name are ignored', () => {
  for (const raw of ['', '   ', null, undefined]) {
    const checked = checkName(raw);
    assert.equal(checked.state, 'empty');
    assert.equal(checked.message, '');
  }
  assert.equal(checkName('  alpha  ').name, 'alpha');
});

test('capitals are lowercased, as the arena reads them', () => {
  assert.equal(foldName('Team-A'), 'team-a');
  const checked = checkName('MyBot_9');
  assert.equal(checked.state, 'valid');
  assert.equal(checked.name, 'mybot_9');
});

test('the link is the form address plus the name', () => {
  assert.equal(registerLink(FORM, 'alpha-1'), `${FORM}alpha-1`);
  assert.equal(registerLink(FORM, 'My_Team'), `${FORM}my_team`);
  assert.equal(registerLink(FORM, 'a'.repeat(32)), FORM + 'a'.repeat(32));
});

test('a name that would need encoding never reaches the link', () => {
  // Valid names are all URL-safe, so nothing to encode; anything else is refused.
  for (const bad of ['a&entry.1=evil', 'a b', 'a#b', 'a=b', 'a?b', 'a%20b', 'é', 'a/../b', '']) {
    assert.equal(registerLink(FORM, bad), null, bad);
  }
  const link = registerLink(FORM, 'a_b-c');
  assert.equal(link, FORM + encodeURIComponent('a_b-c'));
  assert.equal(new URL(link).searchParams.get('entry.123456789'), 'a_b-c');
});

test('no link without a usable form address', () => {
  const bad = [
    null,
    undefined,
    '',
    42,
    'not a url=',
    'http://docs.google.com/forms/d/e/x/viewform?entry.1=',
    'https://example.com/forms/d/e/x/viewform?entry.1=',
    'https://docs.google.com.evil.example/forms/d/e/x/viewform?entry.1=',
    'https://docs.google.com@evil.example/forms/d/e/x/viewform?entry.1=',
    'https://user:pw@docs.google.com/forms/d/e/x/viewform?entry.1=',
    'https://docs.google.com:8443/forms/d/e/x/viewform?entry.1=',
    'https://docs.google.com/document/d/x/edit?entry.1=',
    'https://docs.google.com/forms/d/e/x/viewform?entry.1',
    'https://docs.google.com/forms/d/e/x/viewform?entry.1= ',
    'javascript:alert(1)//docs.google.com/forms/=',
  ];
  for (const form of bad) {
    assert.equal(formAddress(form), null, String(form));
    assert.equal(registerLink(form, 'alpha'), null, String(form));
  }
  assert.equal(formAddress(FORM), FORM);
});

test('listed names: submitted, registered, and an old export counts as submitted', () => {
  assert.deepEqual(listedTeam(TEAMS, 'alpha'), { team: 'alpha', status: 'submitted' });
  assert.deepEqual(listedTeam(TEAMS, 'BRAVO'), { team: 'bravo', status: 'registered' });
  assert.deepEqual(listedTeam(TEAMS, 'old-export'), { team: 'old-export', status: 'submitted' });
  assert.equal(listedTeam(TEAMS, 'charlie'), null);
  assert.equal(listedTeam([], 'alpha'), null);
  assert.equal(listedTeam(undefined, 'alpha'), null);
});

test('state: empty gives no link and no message', () => {
  const s = registerState(FORM, TEAMS, '');
  assert.equal(s.link, null);
  assert.equal(s.message, '');
  assert.equal(s.check.state, 'empty');
});

test('state: a new valid name can be registered', () => {
  const s = registerState(FORM, TEAMS, 'Charlie');
  assert.equal(s.link, `${FORM}charlie`);
  assert.equal(s.listed, null);
  assert.match(s.message, /not listed yet/);
});

test('state: a listed name cannot be registered again, and the page says which kind', () => {
  const sub = registerState(FORM, TEAMS, 'alpha');
  assert.equal(sub.link, null);
  assert.match(sub.message, /already listed \(submitted\)/);
  const reg = registerState(FORM, TEAMS, 'bravo');
  assert.equal(reg.link, null);
  assert.match(reg.message, /already listed \(registered\)/);
  assert.equal(registerState(FORM, TEAMS, 'ALPHA').link, null);
});

test('state: an invalid name has no link and a message', () => {
  const s = registerState(FORM, TEAMS, 'no good');
  assert.equal(s.link, null);
  assert.match(s.message, /space/);
});

test('state: no form (null, or an unusable address) means no link at all', () => {
  assert.equal(registerState(null, TEAMS, 'charlie').link, null);
  const s = registerState('https://example.com/x=', TEAMS, 'charlie');
  assert.equal(s.link, null);
  assert.match(s.message, /form address/);
});
