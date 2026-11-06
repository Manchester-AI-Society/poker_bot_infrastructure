import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  CODE_PLACEHOLDER,
  NO_CODE,
  NO_SERVER,
  SERVER_PLACEHOLDER,
  clean,
  connectInfo,
  howItWorks,
  powershellString,
  safeHref,
  serverBase,
  shellWord,
} from '../../arena/site/js/info-core.js';

const real = JSON.parse(readFileSync(new URL('./fixtures/live/info.json', import.meta.url), 'utf8'));

test('commands are built from the real info.json', () => {
  const c = connectInfo({ ...real, join_code: 'sesame' });
  assert.equal(c.server, real.server_url);
  assert.equal(c.hasServer, true);
  assert.equal(c.code, 'sesame');
  assert.equal(
    c.commands.register.bash,
    `curl -X POST ${real.server_url}/v1/register -H 'Content-Type: application/json' -d '{"player_id": "YOUR-TEAM-NAME", "code": "sesame"}'`,
  );
  assert.equal(
    c.commands.register.powershell,
    `Invoke-RestMethod -Method Post -Uri '${real.server_url}/v1/register' -ContentType 'application/json' -Body '{"player_id": "YOUR-TEAM-NAME", "code": "sesame"}'`,
  );
  assert.equal(c.commands.run, `python -m player_sdk my_bot.py --tournament --server-url ${real.server_url} --api-key <your key>`);
});

test('no join code: the sentence and YOUR-CODE; no server: the announcement and a placeholder', () => {
  const c = connectInfo(real); // the sample has a server and no code
  assert.equal(real.join_code, null);
  assert.equal(c.hasCode, false);
  assert.equal(c.codeLine, NO_CODE);
  assert.equal(NO_CODE, 'Ask the organiser for the join code.');
  assert.ok(c.commands.register.bash.includes(`"code": "${CODE_PLACEHOLDER}"`));
  const none = connectInfo({ server_url: null, join_code: null });
  assert.equal(none.hasServer, false);
  assert.equal(none.serverLine, NO_SERVER);
  assert.equal(NO_SERVER, 'The organiser will announce the server address.');
  assert.ok(none.commands.register.bash.includes(`${SERVER_PLACEHOLDER}/v1/register`));
  assert.ok(none.commands.run.includes(`--server-url ${SERVER_PLACEHOLDER}`));
  assert.equal(connectInfo(null).server, null);
});

test('a trailing slash on the address is dropped', () => {
  assert.equal(serverBase({ server_url: 'https://x.test///' }), 'https://x.test');
  assert.ok(connectInfo({ server_url: 'https://x.test/' }).commands.register.bash.includes('https://x.test/v1/register'));
});

test('hostile values stay one quoted word and cannot add a command', () => {
  const evil = "x'; rm -rf ~; echo '";
  assert.equal(shellWord(evil), "'x'\\''; rm -rf ~; echo '\\'''");
  const c = connectInfo({ server_url: `https://e.test/${evil}`, join_code: `"},"admin":true,"x":"\n${evil}` });
  assert.ok(c.commands.register.bash.startsWith("curl -X POST 'https://e.test/x'\\''; rm -rf ~; echo '\\''/v1/register'"));
  // No newline survives, and the code is JSON-escaped so its quotes stay inside the string.
  assert.ok(!c.commands.register.bash.includes('\n'));
  const body = c.commands.register.bash.split(' -d ')[1];
  assert.ok(body.includes('\\"},\\"admin\\":true'));
  assert.equal(powershellString("a'b"), "'a''b'");
  assert.ok(!c.commands.run.includes('\n'));
  assert.ok(c.commands.register.powershell.includes("''"));
});

test('control characters are removed from everything that goes into a command', () => {
  assert.equal(clean('a\nb\u0000c\r'), 'abc');
  assert.equal(clean(5), '');
  const c = connectInfo({ server_url: 'https://x.test\n; ls', join_code: 'a\tb' });
  assert.ok(!/[\n\r\t]/.test(Object.values(c.commands.register).join('') + c.commands.run));
});

test('only http and https addresses become links', () => {
  assert.equal(safeHref('https://forms.gle/EXAMPLE'), 'https://forms.gle/EXAMPLE');
  assert.equal(safeHref('javascript:alert(1)'), null);
  assert.equal(safeHref('data:text/html,hi'), null);
  assert.equal(safeHref('not a url'), null);
  assert.equal(safeHref(null), null);
});

test('how this site works uses the delay and the update interval', () => {
  const text = howItWorks({ delay_seconds: 360, interval_seconds: 300 }).join(' ');
  assert.match(text, /about 6 minutes behind/);
  assert.match(text, /about every 5 minutes/);
  assert.match(text, /Hole cards are shown only when a hand reaches a showdown/);
  assert.match(howItWorks({}, { delay_seconds: 60 }).join(' '), /about 60 seconds behind/);
  assert.ok(howItWorks(null).length >= 3);
});
