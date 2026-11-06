// Loads the exported JSON. The manifest is tiny and fetched fresh on every
// poll; the bigger files are fetched only when its fingerprint changes, and
// are keyed by it so a CDN or browser can cache them between changes.

import { isTournament, normalizeTeams, normalizeTournament, tournamentFiles } from './tournament-core.js';
import { normalizeEvent } from './event-core.js';

export const data = {
  manifest: null,
  tournament: null, // tournament.json, normalised; null in the ladder format
  boards: {},
  pairings: {},
  teams: [],
  registrations: [],
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

/** Like getJSON, but a file that is not there (404) is null, not an error. */
async function getOptionalJSON(path, bust) {
  const response = await fetch(`${path}?v=${encodeURIComponent(bust)}`, {
    cache: 'no-store',
  });
  if (response.status === 404) return null;
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

/**
 * The tournament format: tournament.json always, and pairings / the final
 * board only for the rounds the manifest says are published. Nothing else is
 * requested, so a not-yet-played round costs no 404s.
 */
async function loadTournament(manifest) {
  const bust = manifest.fingerprint;
  const files = tournamentFiles(manifest);
  const pairingKinds = Object.keys(files.pairings);
  const boardKinds = Object.keys(files.boards);
  const [tournament, teams, event, ...rest] = await Promise.all([
    getJSON(files.tournament, bust),
    getOptionalJSON(files.teams, bust),
    manifest.has_event ? getOptionalJSON('data/event.json', bust) : null,
    ...pairingKinds.map((kind) => getOptionalJSON(files.pairings[kind], bust)),
    ...boardKinds.map((kind) => getOptionalJSON(files.boards[kind], bust)),
  ]);
  data.pairings = {};
  data.boards = {};
  pairingKinds.forEach((kind, index) => {
    data.pairings[kind] = rest[index] || [];
  });
  boardKinds.forEach((kind, index) => {
    const board = rest[pairingKinds.length + index];
    if (board) data.boards[kind] = board;
  });
  data.tournament = normalizeTournament(tournament);
  data.event = normalizeEvent(event);
  data.teams = normalizeTeams(teams && teams.teams);
  data.registrations = [];
  data.manifest = manifest;
  replayCache.clear();
}

async function loadAll(manifest) {
  if (isTournament(manifest)) return loadTournament(manifest);
  data.tournament = null;
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
  data.registrations = teams.registrations || [];
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
