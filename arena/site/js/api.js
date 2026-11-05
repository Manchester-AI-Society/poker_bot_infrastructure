// Loads the exported JSON. The manifest is tiny and fetched fresh on every
// poll; the bigger files are fetched only when its fingerprint changes, and
// are keyed by it so a CDN or browser can cache them between changes.

export const data = {
  manifest: null,
  boards: {},
  pairings: {},
  teams: [],
  lastOk: 0, // wall-clock ms of the last successful poll
  error: null,
};

const replayCache = new Map();

async function getJSON(path, bust) {
  const response = await fetch(`${path}?v=${encodeURIComponent(bust)}`, {
    cache: 'no-store',
  });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

/** Polls the manifest; resolves true when the data changed. */
export async function refresh() {
  try {
    const manifest = await getJSON('data/manifest.json', Date.now());
    data.lastOk = Date.now();
    data.error = null;
    if (data.manifest && data.manifest.fingerprint === manifest.fingerprint) {
      return false;
    }
    await loadAll(manifest);
    return true;
  } catch (error) {
    data.error = error;
    console.warn('Could not load results:', error);
    return false;
  }
}

async function loadAll(manifest) {
  const bust = manifest.fingerprint;
  const kinds = manifest.kinds || ['ladder'];
  const [teams, ...rest] = await Promise.all([
    getJSON('data/teams.json', bust),
    ...kinds.flatMap((kind) => [
      getJSON(`data/leaderboard-${kind}.json`, bust),
      getJSON(`data/pairings-${kind}.json`, bust),
    ]),
  ]);
  data.boards = {};
  data.pairings = {};
  kinds.forEach((kind, index) => {
    data.boards[kind] = rest[index * 2];
    data.pairings[kind] = rest[index * 2 + 1];
  });
  data.teams = teams.teams;
  data.manifest = manifest;
  replayCache.clear(); // replay files may have been rebuilt
}

/** The how-to-submit guide as markdown text (cached until the data changes). */
let guideCache = null;
export async function loadGuide() {
  const bust = data.manifest ? data.manifest.fingerprint : '0';
  if (!guideCache || guideCache.bust !== bust) {
    const response = await fetch(`data/submitting.md?v=${encodeURIComponent(bust)}`, {
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`data/submitting.md: HTTP ${response.status}`);
    guideCache = { bust, text: await response.text() };
  }
  return guideCache.text;
}

export async function loadReplay(path) {
  if (!replayCache.has(path)) {
    const bust = data.manifest ? data.manifest.fingerprint : '0';
    replayCache.set(path, getJSON(path, bust));
  }
  try {
    return await replayCache.get(path);
  } catch (error) {
    replayCache.delete(path);
    throw error;
  }
}

/** All pairings across kinds, newest first. */
export function allPairings() {
  return Object.values(data.pairings)
    .flat()
    .sort((a, b) => (b.finished_at || 0) - (a.finished_at || 0));
}

export function findPairing(id) {
  return allPairings().find((p) => p.id === id) || null;
}

export function teamEntry(name) {
  return data.teams.find((t) => t.team === name) || null;
}

export function boardRow(kind, name) {
  const board = data.boards[kind];
  return board ? board.teams.find((t) => t.team === name) || null : null;
}
