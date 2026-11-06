// Pure helpers for the live format (manifest.mode === "live"): the data
// shapes, the words for each status, and which table to feature. Nothing here
// touches the DOM, so Node can test it (tests/site_js).
//
// Every string in the data (names, notes, end reasons) is untrusted text; it
// is only ever handed on, never interpreted.

import { ago } from './format.js';

export const LIVE_STATUSES = ['idle', 'starting', 'running', 'finished'];
export const TEAM_STATUSES = ['registered', 'in the lobby', 'playing', 'out', 'champion'];

const SAFE_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function isLive(manifest) {
  return Boolean(manifest) && manifest.mode === 'live';
}

/** The Register page in the live format exists only when the organiser set a form. */
export function liveRegisterForm(manifest) {
  return isLive(manifest) && manifest.register_form ? manifest.register_form : null;
}

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const number = (value, fallback = null) => (typeof value === 'number' && Number.isFinite(value) ? value : fallback);
const text = (value) => (typeof value === 'string' ? value : '');
const list = (value) => (Array.isArray(value) ? value : []);
const names = (value) => list(value).filter((x) => typeof x === 'string');

function normalizeTable(raw) {
  const t = isObject(raw) ? raw : {};
  const stacks = {};
  if (isObject(t.stacks)) {
    for (const [name, chips] of Object.entries(t.stacks)) if (number(chips) !== null) stacks[name] = chips;
  }
  const level = isObject(t.level) && number(t.level.small) !== null && number(t.level.big) !== null ? { small: t.level.small, big: t.level.big } : null;
  return {
    match_id: text(t.match_id),
    round: number(t.round, 1),
    players: names(t.players),
    status: t.status === 'finished' ? 'finished' : 'playing',
    winners: names(t.winners),
    end_reason: text(t.end_reason) || null,
    hands_played: number(t.hands_played, 0),
    stacks,
    eliminated: names(t.eliminated),
    starting_stack: number(t.starting_stack),
    level,
  };
}

/** live.json with every field present and the right type, whatever the file held. */
export function normalizeLive(raw, manifest = null) {
  const l = isObject(raw) ? raw : {};
  const fallbackDelay = manifest && number(manifest.delay_seconds) !== null ? manifest.delay_seconds : 0;
  return {
    status: LIVE_STATUSES.includes(l.status) ? l.status : 'idle',
    delay_seconds: number(l.delay_seconds, fallbackDelay),
    visible_until: number(l.visible_until),
    round: number(l.round, 0),
    rounds: list(l.rounds)
      .filter(isObject)
      .map((r) => ({ round: number(r.round, 1), tables: list(r.tables).filter(isObject).map(normalizeTable) })),
    champion: typeof l.champion === 'string' && l.champion ? l.champion : null,
    entrants: names(l.entrants),
    lobby: names(l.lobby),
  };
}

/** info.json with every field present: strings or null, a note that is a string. */
export function normalizeInfo(raw, manifest = null) {
  const i = isObject(raw) ? raw : {};
  const str = (v) => (typeof v === 'string' && v.trim() ? v.trim() : null);
  return {
    server_url: str(i.server_url),
    join_code: str(i.join_code),
    form_url: str(i.form_url),
    delay_seconds: number(i.delay_seconds, manifest && number(manifest.delay_seconds) !== null ? manifest.delay_seconds : null),
    interval_seconds: number(i.interval_seconds),
    note: typeof i.note === 'string' ? i.note.trim() : '',
  };
}

/** teams.json's list for the live format: {team, status}, status one of TEAM_STATUSES. */
export function normalizeLiveTeams(list_) {
  return list(list_)
    .filter((e) => isObject(e) && typeof e.team === 'string')
    .map((e) => ({ ...e, status: TEAM_STATUSES.includes(e.status) ? e.status : 'registered' }));
}

/** Every table file the page may request: only match ids that are plain ids. */
export function tableIds(live) {
  const seen = new Set();
  for (const round of live.rounds) {
    for (const table of round.tables) if (SAFE_ID.test(table.match_id)) seen.add(table.match_id);
  }
  return [...seen];
}

export function tableFile(id) {
  return `data/tables/${id}.json`;
}

// ---- words -------------------------------------------------------------

/** "about 6 minutes", "about 1 minute", "about 30 seconds"; '' when unknown. */
export function delayText(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '';
  if (seconds < 90) {
    const s = Math.max(0, Math.round(seconds));
    return `about ${s} ${s === 1 ? 'second' : 'seconds'}`;
  }
  const minutes = Math.round(seconds / 60);
  return `about ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
}

/** The notice shown on every live page. */
export function delayNotice(seconds) {
  const when = delayText(seconds);
  return when ? `This stream runs ${when} behind the real game.` : 'This stream runs behind the real game.';
}

/** "The site updates about every 5 minutes." */
export function intervalText(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return '';
  if (seconds < 90) return `about every ${Math.round(seconds)} seconds`;
  const minutes = Math.round(seconds / 60);
  return `about every ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
}

/** The status line shown while waiting at the live edge. */
export function waitingText(seconds) {
  const when = delayText(seconds);
  return when ? `Waiting for the next update… the feed is ${when} behind.` : 'Waiting for the next update…';
}

export function plainCount(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

/** The label of a table: "Final table" when it is all that is left after round 1. */
export function tableLabel(round, index) {
  return round.tables.length === 1 && round.round > 1 ? 'Final table' : `Table ${index + 1}`;
}

/** All visible tables as {table, round, label}, in round order. */
export function allTables(live) {
  const out = [];
  for (const round of live.rounds) {
    round.tables.forEach((table, index) => out.push({ table, round: round.round, label: tableLabel(round, index) }));
  }
  return out;
}

/** The label of one table by id, or its id when unknown. */
export function labelOf(live, id) {
  const found = allTables(live).find((x) => x.table.match_id === id);
  return found ? found.label : id;
}

/**
 * What the banner at the top of the live home page says: {label, text, tone}.
 * Nothing is claimed that the data does not hold.
 */
export function statusBanner(live) {
  const delay = delayText(live.delay_seconds);
  switch (live.status) {
    case 'finished':
      return {
        label: 'Finished',
        text: live.champion ? `The tournament is over. The champion is ${live.champion}.` : 'The tournament is over.',
      };
    case 'running': {
      const current = live.rounds.find((r) => r.round === live.round) || live.rounds[live.rounds.length - 1];
      const tables = current ? current.tables : [];
      const playing = tables.filter((t) => t.status === 'playing').length;
      const left = new Set();
      for (const t of tables) for (const p of t.players) if (!t.eliminated.includes(p)) left.add(p);
      const final = tables.length === 1 && live.round > 1;
      const where = final ? 'The final table is playing' : `Round ${live.round} is in progress`;
      const parts = [where];
      if (tables.length) parts.push(`${plainCount(playing, 'table')} playing of ${tables.length}`);
      if (left.size && !final) parts.push(`${plainCount(left.size, 'player')} still in`);
      return { label: final ? 'Final' : `Round ${live.round}`, text: `${parts.join(' · ')}.` };
    }
    case 'starting':
      return {
        label: 'Starting',
        text: `The tournament has started. Play appears on this page shortly: the feed runs ${delay || 'a while'} behind the real game.`,
      };
    default:
      return { label: 'Waiting', text: 'Waiting for players. The tournament has not started.' };
  }
}

// ---- tables ------------------------------------------------------------

/** The newest hand end time of a table file, or null without hands. */
export function latestEnd(tableFileData) {
  const hands = tableFileData && Array.isArray(tableFileData.hands) ? tableFileData.hands : [];
  let best = null;
  for (const hand of hands) if (number(hand && hand.end) !== null && (best === null || hand.end > best)) best = hand.end;
  return best;
}

/**
 * The table to show first: among the tables with hands, a table still
 * playing beats a finished one, then the most recent hand wins; ties go to
 * the later round. Null when no table has a hand to show.
 */
export function pickFeatured(live, tablesById, skip = () => false) {
  let best = null;
  for (const entry of allTables(live)) {
    if (skip(entry.table.match_id)) continue;
    const file = tablesById[entry.table.match_id];
    const end = latestEnd(file);
    if (end === null) continue;
    const key = [entry.table.status === 'playing' ? 1 : 0, end, entry.round];
    if (!best || compareKeys(key, best.key) > 0) best = { id: entry.table.match_id, key };
  }
  return best ? best.id : null;
}

function compareKeys(a, b) {
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

/**
 * Keeps the table being shown while it is still worth watching; picks anew
 * when it is gone or has finished and its playback has reached the end.
 * `choice` is a table the visitor picked: it always wins while it exists.
 */
export function chooseShown(live, tablesById, { choice = null, current = null, finishedAndSeen = () => false } = {}) {
  const entries = allTables(live);
  const exists = (id) => id && tablesById[id] && entries.some((x) => x.table.match_id === id);
  if (exists(choice)) return choice;
  const done = (id) => entries.some((x) => x.table.match_id === id && x.table.status === 'finished') && finishedAndSeen(id);
  if (exists(current) && !done(current)) return current;
  // Move on, but never back to a table that has finished and been watched to its end.
  const next = pickFeatured(live, tablesById, done);
  return next || (exists(current) ? current : pickFeatured(live, tablesById));
}

/** The players of a table card with their chips and a state in words. */
export function tablePlayers(table) {
  const winners = new Set(table.winners);
  const out = new Set(table.eliminated);
  return table.players.map((name) => {
    const chips = table.stacks[name];
    let state = '';
    if (winners.has(name)) state = 'winner';
    else if (out.has(name) || chips === 0) state = 'out';
    return { name, chips: chips === undefined ? null : chips, state };
  });
}

/** One line about a table's state: "playing", "finished: X won". */
export function tableStateText(table) {
  if (table.status !== 'finished') return 'playing';
  const who = table.winners.length ? ` — ${table.winners.join(', ')} won` : '';
  return `finished${who}`;
}

// ---- teams -------------------------------------------------------------

/** What each team status means, in one line (so the badges are not guesses). */
export const LIVE_STATUS_LEGEND =
  'registered: the name is listed. in the lobby: the bot is connected and waiting. playing: the bot has a seat. out: knocked out. champion: won the tournament.';

const BADGE = {
  registered: 'badge',
  'in the lobby': 'badge ok',
  playing: 'badge ok',
  out: 'badge prov',
  champion: 'badge final mark',
};

export function teamBadge(status) {
  return { cls: BADGE[status] || 'badge', text: status };
}

/** Counts per status, for the summary line. */
export function teamCounts(teams) {
  const counts = {};
  for (const t of teams) counts[t.status] = (counts[t.status] || 0) + 1;
  return counts;
}

/** "3 playing, 2 out, 5 registered" in the order of TEAM_STATUSES; empty ones left out. */
export function teamSummary(teams) {
  const counts = teamCounts(teams);
  return TEAM_STATUSES.filter((s) => counts[s]).map((s) => `${counts[s]} ${s}`).join(', ');
}

/** The footer text, as in the other formats. */
export function liveUpdatedText(ageSeconds, { stale = false } = {}) {
  const changed = ago(ageSeconds);
  return stale ? `Connection lost – showing data from ${changed}` : `Updated ${changed}`;
}

// ---- the table, in words -------------------------------------------------

/** The status line under the table: what the playback is doing, in plain words. */
export function playbackStatus({ state, behind = 0, catchUp = 1, delay = null, winners = [] }) {
  switch (state) {
    case 'empty':
      return 'No hands are visible for this table yet.';
    case 'waiting':
      return waitingText(delay);
    case 'finished':
      return winners.length ? `This table has finished: ${winners.join(', ')} won.` : 'This table has finished.';
    case 'paused':
      return behind > 0 ? `Paused · ${plainCount(behind, 'hand')} behind the live edge` : 'Paused';
    default:
      if (behind <= 0) return 'Playing · at the live edge of the feed';
      return `Playing · ${plainCount(behind, 'hand')} behind the live edge${catchUp > 1.05 ? ` (catching up, ${catchUp.toFixed(1)}×)` : ''}`;
  }
}

/**
 * What a seat says about itself, in words (never by colour alone):
 *   {text, bet}. `text` is the strongest of: wins, out, the hand shown at the
 *   showdown, folded, all in, to act, or the last action; `bet` is the chips
 *   it has in this street, or 0.
 */
export function seatStatus(seat, toAct = false) {
  const chips = (n) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  let text = '';
  if (seat.winner) text = `wins ${chips(seat.winnings)}`;
  else if (seat.state === 'out') text = seat.note === 'eliminated' ? 'eliminated' : 'out';
  else if (seat.hole && seat.hand) text = seat.hand;
  else if (seat.state === 'folded') text = 'folded';
  else if (seat.state === 'allin') text = 'all in';
  else if (toAct) text = 'to act';
  else text = seat.note || '';
  return { text, bet: seat.bet > 0 ? seat.bet : 0 };
}
