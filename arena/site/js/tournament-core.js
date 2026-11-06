// Pure helpers for the two-round tournament (groups, then finals). Nothing
// here touches the DOM, so Node can test it (tests/site_js).
//
// The exporter publishes nothing about how anyone is doing until a round is
// complete: before that the data holds only the draw and the phase. These
// helpers therefore treat every result field as possibly missing, and say
// "results are shown when the round is complete" instead of showing zeros.

import { ago } from './format.js';

export const NOT_YET = 'Results are shown when the round is complete.';

const PHASES = {
  registration: {
    label: 'Submissions',
    text: 'Submissions are open: teams are handing in their bots.',
  },
  drawn: {
    label: 'Groups drawn',
    text: 'The groups have been drawn. Play has not started yet.',
  },
  groups: {
    label: 'Round 1',
    text: 'Round 1 (groups) is in progress. Results are shown when the round ends.',
  },
  between: {
    label: 'Between rounds',
    text: 'Round 1 is complete. The finals are about to start.',
  },
  finals: {
    label: 'Finals',
    text: 'The finals are in progress. Results are shown when the round ends.',
  },
  done: {
    label: 'Finished',
    text: 'The tournament is finished.',
  },
};

export const PHASE_ORDER = Object.keys(PHASES);

export function isTournament(manifest) {
  return Boolean(manifest) && manifest.mode === 'tournament';
}

/**
 * The registration form's address when this event has a team-name
 * registration (tournament mode and a form set), else null.
 */
export function registerFormOpen(manifest) {
  return isTournament(manifest) && manifest.register_form ? manifest.register_form : null;
}

/** {phase, label, text, known} for a phase name; unknown names stay readable. */
export function phaseInfo(phase) {
  const info = PHASES[phase];
  if (info) return { phase, ...info, known: true };
  return { phase: phase || '', label: 'Tournament', text: 'The tournament is under way.', known: false };
}

/** A tournament.json payload with every field present, whatever was missing. */
export function normalizeTournament(raw) {
  const t = raw && typeof raw === 'object' ? raw : {};
  const advance = Number.isInteger(t.advance) && t.advance > 0 ? t.advance : 2;
  const board = (b) => (b && Array.isArray(b.teams) ? b : null);
  return {
    phase: t.phase || '',
    // One round (a single round robin, no finals) or the usual two.
    rounds: t.rounds === 1 ? 1 : 2,
    advance,
    groups: Array.isArray(t.groups)
      ? t.groups.map((g) => ({
          name: String(g.name),
          teams: Array.isArray(g.teams) ? g.teams : [],
          board: board(g.board),
        }))
      : [],
    qualified: Array.isArray(t.qualified) ? t.qualified : [],
    finals: t.finals
      ? { teams: Array.isArray(t.finals.teams) ? t.finals.teams : [], board: board(t.finals.board) }
      : null,
    champion: t.champion || null,
  };
}

/**
 * The status of a teams.json entry: 'submitted' (a bot with that name has
 * arrived, so the name is confirmed) or 'registered' (only the name is listed).
 * An export that predates the field has only teams with bots: 'submitted'.
 */
export function entryStatus(entry) {
  return entry && entry.status === 'registered' ? 'registered' : 'submitted';
}

/** teams.json's list with `status` always present, sorted by name like the export. */
export function normalizeTeams(list) {
  if (!Array.isArray(list)) return [];
  return list.map((entry) => ({ ...entry, status: entryStatus(entry) }));
}

/** The listed teams that are in no group (registered, or submitted after the draw), in order. */
export function undrawnTeams(teams, t) {
  const drawn = new Set(t.groups.flatMap((g) => g.teams));
  return (teams || []).filter((entry) => !drawn.has(entry.team));
}

/** How many of the listed teams have a bot ('submitted') and how many only a name. */
export function statusCounts(teams) {
  const list = teams || [];
  const submitted = list.filter((e) => entryStatus(e) === 'submitted').length;
  return { submitted, registered: list.length - submitted };
}

/** The data files to fetch: only those the manifest says exist. */
export function tournamentFiles(manifest) {
  const kinds = (manifest && manifest.kinds) || [];
  const files = { tournament: 'data/tournament.json', teams: 'data/teams.json', pairings: {}, boards: {} };
  for (const kind of kinds) {
    if (kind === 'group' || kind === 'final') files.pairings[kind] = `data/pairings-${kind}.json`;
    // Group boards travel inside tournament.json; only the final has its own file.
    if (kind === 'final') files.boards.final = 'data/leaderboard-final.json';
  }
  return files;
}

/** Whether round 1 has been published (any group has a ranked table). */
export function groupsRevealed(t) {
  return t.groups.some((g) => g.board);
}

/**
 * The boards a visitor can look at, in order: each revealed group, then the
 * finals. `finalBoard` (from leaderboard-final.json) wins over the copy in
 * tournament.json when both exist.
 */
export function revealedBoards(t, finalBoard = null) {
  const out = t.groups
    .filter((g) => g.board)
    .map((g) => ({ id: g.name, label: `Group ${g.name}`, kind: 'group', board: g.board }));
  const board = finalBoard || (t.finals && t.finals.board) || null;
  if (board) out.push({ id: 'final', label: 'Finals', kind: 'final', board });
  return out;
}

/** 'unknown' (round 1 not done), 'known' (finalists named), 'playing', 'result'. */
export function finalsStage(t) {
  if (t.finals && t.finals.board) return 'result';
  if (t.finals) return 'playing';
  if (t.qualified.length) return 'known';
  return 'unknown';
}

/** "The best 2 of each group play a round robin to decide the champion." */
export function advanceText(advance) {
  if (advance === 1) {
    return 'The winner of each group plays in a round robin to decide the champion.';
  }
  return `The best ${advance} of each group play a round robin to decide the champion.`;
}

/** What to say under the Round 1 heading, or null once results are shown. */
export function roundOneNote(t) {
  if (groupsRevealed(t)) return null;
  if (t.rounds === 1 && t.phase === 'registration') return 'The draw is made when submissions close. Everyone plays everyone in one round.';
  switch (t.phase) {
    case 'registration':
      return 'The groups are drawn when submissions close.';
    case 'drawn':
      return `Round 1 has not started. ${NOT_YET}`;
    case 'groups':
      return `Round 1 is in progress. ${NOT_YET}`;
    default:
      return NOT_YET;
  }
}

/** What to say under the Finals heading, or null once results are shown. */
export function finalsNote(t) {
  const stage = finalsStage(t);
  if (stage === 'unknown') return `${advanceText(t.advance)} The finalists are known when Round 1 is complete.`;
  if (stage === 'known') return `${advanceText(t.advance)} The finals are about to start. ${NOT_YET}`;
  if (stage === 'playing') return `The finals are in progress. ${NOT_YET}`;
  return null;
}

/**
 * Which teams of a group get the "Qualified" mark. The exporter's own list
 * wins (it applies the real tie-breaks); without it the top `advance` ranked
 * rows are marked. A group smaller than `advance` marks everyone ranked.
 */
export function qualifiedInGroup(group, t) {
  const out = new Set();
  if (!group.board) return out;
  if (t.qualified.length) {
    for (const row of group.board.teams) if (t.qualified.includes(row.team)) out.add(row.team);
    return out;
  }
  const ranked = group.board.teams.filter((row) => row.score != null);
  for (const row of ranked.slice(0, t.advance)) out.add(row.team);
  return out;
}

/** Marks for a group table: team name -> text. */
export function groupMarks(group, t) {
  // One round: the champion is the top of the table; nobody "qualifies".
  if (t.rounds === 1) return t.champion && group.teams.includes(t.champion) ? new Map([[t.champion, 'Champion']]) : new Map();
  return new Map([...qualifiedInGroup(group, t)].map((name) => [name, 'Qualified']));
}

/** Marks for the finals table: the champion, if known. */
export function finalMarks(t) {
  return t.champion ? new Map([[t.champion, 'Champion']]) : new Map();
}

/**
 * Where one team stands. Everything result-like is null until revealed.
 * `qualified` is null while unknown, then true or false.
 */
export function teamStanding(name, t) {
  const group = t.groups.find((g) => g.teams.includes(name)) || null;
  const groupRow = group && group.board ? group.board.teams.find((r) => r.team === name) || null : null;
  const finalsBoard = t.finals && t.finals.board;
  const finalRow = finalsBoard ? finalsBoard.teams.find((r) => r.team === name) || null : null;
  return {
    group: group ? group.name : null,
    groupSize: group ? group.teams.length : 0,
    groupRow,
    qualified: t.qualified.length ? t.qualified.includes(name) : null,
    inFinals: t.finals ? t.finals.teams.includes(name) : null,
    finalRow,
    champion: t.champion === name,
  };
}

/** The "last updated" label for the header, and when the link is stale. */
export function updatedText(manifest, ageSeconds, { stale = false } = {}) {
  const changed = ago(ageSeconds);
  if (isTournament(manifest)) {
    // There is no live result in this format, so never claim a "last result".
    return stale ? `Connection lost – showing data from ${changed}` : `Updated ${changed}`;
  }
  return stale ? `Connection lost – showing results from ${changed}` : `Last result ${changed}`;
}
