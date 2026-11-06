import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { data, refresh } from '../../arena/site/js/api.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/live/${name}.json`, import.meta.url), 'utf8'));

/** A fake server: `files` maps a path to its JSON; anything else is a 404. */
function serve(files) {
  const requested = [];
  globalThis.fetch = async (url) => {
    const path = String(url).split('?')[0];
    requested.push(path);
    if (!(path in files)) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => files[path] };
  };
  return requested;
}

const manifest = (fingerprint, extra = {}) => ({ mode: 'live', title: 't', has_guide: false, register_form: null, fingerprint, generated_at: 1, kinds: [], teams: 1, delay_seconds: 30, ...extra });
const live = fixture('live-finished');
const ids = live.rounds.flatMap((r) => r.tables.map((t) => t.match_id));

test('only the files live.json lists are requested; every table that exists is loaded', async () => {
  const final = fixture('final-3-handed');
  const requested = serve({
    'data/manifest.json': manifest('one'),
    'data/live.json': live,
    'data/info.json': fixture('info'),
    'data/teams.json': { teams: [{ team: 'a', status: 'playing' }] },
    [`data/tables/${final.match_id}.json`]: final,
    'data/tables/d12c06147c10.json': fixture('heads-up'),
  });
  data.manifest = null;
  assert.equal(await refresh(), true);
  assert.deepEqual(
    requested.sort(),
    ['data/info.json', 'data/live.json', 'data/manifest.json', 'data/teams.json', ...ids.map((id) => `data/tables/${id}.json`)].sort(),
  );
  assert.equal(data.live.status, 'finished');
  assert.equal(data.live.champion, 'device-5-1793998903');
  assert.equal(data.info.server_url, 'https://example-tunnel.trycloudflare.com');
  assert.deepEqual(data.teams, [{ team: 'a', status: 'playing' }]);
  assert.deepEqual(Object.keys(data.tables).sort(), [final.match_id, 'd12c06147c10'].sort());
  assert.equal(data.tournament, null);
  assert.deepEqual(data.boards, {});
});

test('a table file that is missing (404) is tolerated; so are missing info and teams', async () => {
  serve({ 'data/manifest.json': manifest('two'), 'data/live.json': live });
  data.manifest = null;
  assert.equal(await refresh(), true);
  assert.deepEqual(data.tables, {});
  assert.equal(data.live.rounds.length, 2);
  assert.deepEqual(data.info, { server_url: null, join_code: null, form_url: null, delay_seconds: 30, interval_seconds: null, note: '', event: null });
  assert.deepEqual(data.teams, []);
});

test('before the start there are no tables to request', async () => {
  const requested = serve({
    'data/manifest.json': manifest('lobby'),
    'data/live.json': { status: 'idle', delay_seconds: 30, rounds: [], lobby: ['x'], entrants: [] },
  });
  data.manifest = null;
  await refresh();
  assert.deepEqual(requested.sort(), ['data/info.json', 'data/live.json', 'data/manifest.json', 'data/teams.json']);
  assert.deepEqual(data.live.lobby, ['x']);
});

test('an unchanged fingerprint asks for the manifest only', async () => {
  serve({ 'data/manifest.json': manifest('same'), 'data/live.json': live });
  data.manifest = null;
  await refresh();
  const requested = serve({ 'data/manifest.json': manifest('same') });
  assert.equal(await refresh(), false);
  assert.deepEqual(requested, ['data/manifest.json']);
  // A new fingerprint loads everything again.
  const again = serve({ 'data/manifest.json': manifest('newer'), 'data/live.json': live });
  assert.equal(await refresh(), true);
  assert.ok(again.includes('data/live.json'));
});

test('hostile match ids are never turned into requests', async () => {
  const evil = { ...live, rounds: [{ round: 1, tables: [{ match_id: '../../etc/passwd' }, { match_id: 'ok1' }] }] };
  const requested = serve({ 'data/manifest.json': manifest('evil'), 'data/live.json': evil });
  data.manifest = null;
  await refresh();
  assert.ok(requested.includes('data/tables/ok1.json'));
  assert.ok(!requested.some((p) => p.includes('..')));
});

test('a missing live.json is reported and the next poll tries again', async () => {
  const warn = console.warn;
  console.warn = () => {};
  try {
    serve({ 'data/manifest.json': manifest('late') });
    data.manifest = null;
    assert.equal(await refresh(), false);
    assert.ok(data.error);
    serve({ 'data/manifest.json': manifest('late'), 'data/live.json': live });
    assert.equal(await refresh(), true);
    assert.equal(data.error, null);
  } finally {
    console.warn = warn;
  }
});

test('switching from a live export to another format clears the live data', async () => {
  serve({ 'data/manifest.json': manifest('x1'), 'data/live.json': live });
  data.manifest = null;
  await refresh();
  assert.ok(data.live);
  serve({
    'data/manifest.json': { mode: 'tournament', phase: 'drawn', kinds: [], fingerprint: 'x2', generated_at: 1 },
    'data/tournament.json': { phase: 'drawn', groups: [] },
    'data/teams.json': { teams: [] },
  });
  await refresh();
  assert.equal(data.live, null);
  assert.deepEqual(data.tables, {});
});
