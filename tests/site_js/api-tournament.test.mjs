import test from 'node:test';
import assert from 'node:assert/strict';
import { data, refresh } from '../../arena/site/js/api.js';

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

const tournament = { phase: 'drawn', advance: 2, groups: [{ name: 'A', teams: ['x', 'y'], board: null }], qualified: [], finals: null, champion: null };
const teams = { teams: [{ team: 'x', group: 'A', versions: [] }], registrations: [] };

function manifest(phase, kinds, fingerprint) {
  return { mode: 'tournament', phase, kinds, fingerprint, generated_at: 1 };
}

test('before a round is complete only the manifest, tournament and teams are requested', async () => {
  for (const phase of ['registration', 'drawn', 'groups']) {
    const requested = serve({
      'data/manifest.json': manifest(phase, [], `fp-${phase}`),
      'data/tournament.json': tournament,
      'data/teams.json': teams,
    });
    data.manifest = null;
    assert.equal(await refresh(), true, phase);
    assert.deepEqual(requested.sort(), ['data/manifest.json', 'data/teams.json', 'data/tournament.json'], phase);
    assert.deepEqual(data.pairings, {});
    assert.deepEqual(data.boards, {});
    assert.equal(data.tournament.phase, 'drawn');
    assert.equal(data.teams.length, 1);
  }
});

test('published rounds load their pairings and the final board', async () => {
  const requested = serve({
    'data/manifest.json': manifest('done', ['group', 'final'], 'done'),
    'data/tournament.json': { ...tournament, phase: 'done' },
    'data/teams.json': teams,
    'data/pairings-group.json': [{ id: 'group-1' }],
    'data/pairings-final.json': [{ id: 'final-2' }],
    'data/leaderboard-final.json': { teams: [] },
  });
  data.manifest = null;
  assert.equal(await refresh(), true);
  assert.ok(!requested.some((p) => p.includes('leaderboard-group') || p.includes('ladder')), requested.join());
  assert.deepEqual(data.pairings.group, [{ id: 'group-1' }]);
  assert.deepEqual(data.pairings.final, [{ id: 'final-2' }]);
  assert.deepEqual(data.boards.final, { teams: [] });
});

test('a listed file that is missing (404) does not break the page', async () => {
  serve({
    'data/manifest.json': manifest('between', ['group'], 'gone'),
    'data/tournament.json': { ...tournament, phase: 'between' },
    'data/teams.json': teams,
  });
  data.manifest = null;
  assert.equal(await refresh(), true);
  assert.deepEqual(data.pairings.group, []);
  assert.equal(data.manifest.phase, 'between');
});

test('a missing tournament.json is reported, and the next poll tries again', async () => {
  const original = console.warn;
  console.warn = () => {};
  try {
    serve({ 'data/manifest.json': manifest('drawn', [], 'late') });
    data.manifest = null;
    assert.equal(await refresh(), false);
    assert.ok(data.error);
    serve({
      'data/manifest.json': manifest('drawn', [], 'late'),
      'data/tournament.json': tournament,
      'data/teams.json': teams,
    });
    assert.equal(await refresh(), true);
    assert.equal(data.error, null);
  } finally {
    console.warn = original;
  }
});

test('an unchanged fingerprint fetches nothing but the manifest', async () => {
  const files = {
    'data/manifest.json': manifest('drawn', [], 'same'),
    'data/tournament.json': tournament,
    'data/teams.json': teams,
  };
  serve(files);
  data.manifest = null;
  await refresh();
  const requested = serve(files);
  assert.equal(await refresh(), false);
  assert.deepEqual(requested, ['data/manifest.json']);
});
