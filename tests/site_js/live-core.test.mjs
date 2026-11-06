import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  allTables,
  chooseShown,
  delayNotice,
  delayText,
  intervalText,
  isLive,
  latestEnd,
  liveRegisterForm,
  normalizeEvent,
  normalizeInfo,
  normalizeLive,
  normalizeLiveTeams,
  pickFeatured,
  playbackStatus,
  seatStatus,
  statusBanner,
  tableIds,
  tablePlayers,
  tableStateText,
  teamBadge,
  teamSummary,
  waitingText,
} from '../../arena/site/js/live-core.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/live/${name}.json`, import.meta.url), 'utf8'));
const finished = normalizeLive(fixture('live-finished'));

test('only a manifest in live mode is live; the form is the manifest register_form', () => {
  assert.equal(isLive({ mode: 'live' }), true);
  assert.equal(isLive({ mode: 'tournament' }), false);
  assert.equal(isLive({}), false);
  assert.equal(isLive(null), false);
  assert.equal(liveRegisterForm({ mode: 'live', register_form: 'x=' }), 'x=');
  assert.equal(liveRegisterForm({ mode: 'live', register_form: null }), null);
  assert.equal(liveRegisterForm({ mode: 'ladder', register_form: 'x=' }), null);
});

test('the delay is said in plain words', () => {
  assert.equal(delayText(360), 'about 6 minutes');
  assert.equal(delayText(60), 'about 60 seconds');
  assert.equal(delayText(120), 'about 2 minutes');
  assert.equal(delayText(30), 'about 30 seconds');
  assert.equal(delayText(1), 'about 1 second');
  assert.equal(delayText(null), '');
  assert.equal(delayText(-5), '');
  assert.equal(delayNotice(360), 'This stream runs about 6 minutes behind the real game.');
  assert.equal(delayNotice(undefined), 'This stream runs behind the real game.');
  assert.equal(intervalText(300), 'about every 5 minutes');
  assert.equal(intervalText(60), 'about every 60 seconds');
  assert.equal(intervalText(null), '');
  assert.match(waitingText(360), /Waiting for the next update… the feed is about 6 minutes behind\./);
});

test('live.json is normalised whatever it holds', () => {
  const empty = normalizeLive(null, { delay_seconds: 9 });
  assert.deepEqual(empty, { status: 'idle', delay_seconds: 9, visible_until: null, round: 0, rounds: [], champion: null, entrants: [], lobby: [] });
  const odd = normalizeLive({
    status: 'weird',
    rounds: [{ round: 1, tables: [{ match_id: 'a', players: ['x', 3], stacks: { x: 5, y: 'q' }, winners: 'no' }, 7] }, 'z'],
    lobby: 'no',
    champion: 5,
  });
  assert.equal(odd.status, 'idle');
  assert.equal(odd.champion, null);
  assert.deepEqual(odd.lobby, []);
  assert.equal(odd.rounds.length, 1);
  const table = odd.rounds[0].tables[0];
  assert.deepEqual(table.players, ['x']);
  assert.deepEqual(table.stacks, { x: 5 });
  assert.deepEqual(table.winners, []);
  assert.equal(table.status, 'playing');
  assert.equal(finished.champion, 'device-5-1793998903');
  assert.equal(finished.rounds.length, 2);
});

test('info.json and teams.json are normalised', () => {
  assert.deepEqual(normalizeInfo(null), { server_url: null, join_code: null, form_url: null, delay_seconds: null, interval_seconds: null, note: '', event: null });
  const info = normalizeInfo({ server_url: ' https://x.test ', join_code: '', form_url: 5, note: 7, interval_seconds: 300, delay_seconds: 30 });
  assert.equal(info.server_url, 'https://x.test');
  assert.equal(info.join_code, null);
  assert.equal(info.form_url, null);
  assert.equal(info.note, '');
  assert.deepEqual(normalizeLiveTeams([{ team: 'a', status: 'playing' }, { team: 'b', status: 'bogus' }, { nope: 1 }, 'c']), [
    { team: 'a', status: 'playing' },
    { team: 'b', status: 'registered' },
  ]);
  assert.deepEqual(normalizeLiveTeams(null), []);
});

test('the Home page text keeps only short plain strings and known fields', () => {
  assert.equal(normalizeEvent(null), null);
  assert.equal(normalizeEvent({}), null);
  assert.equal(normalizeEvent([1]), null);
  const event = normalizeEvent({
    tagline: ' Go ',
    intro: ['a', 5, '', ' b '],
    prize: '£300',
    timeline: [{ time: '12:00', title: 'Start', detail: 'd', evil: '<b>' }, { time: '1' }, 'x', { title: 7 }],
    rules: 'not a list',
    contact: 'ask',
    other: 'ignored',
  });
  assert.deepEqual(event, {
    tagline: 'Go',
    intro: ['a', 'b'],
    prize: '£300',
    timeline: [{ time: '12:00', title: 'Start', detail: 'd' }],
    rules: [],
    contact: 'ask',
  });
  assert.equal(normalizeEvent({ prize: 'x'.repeat(500) }).prize.length, 200);
  assert.equal(normalizeInfo({ event: { prize: 'p' } }).event.prize, 'p');
});

test('only plain table ids are ever requested', () => {
  const live = normalizeLive({
    rounds: [{ round: 1, tables: [{ match_id: 'abc123' }, { match_id: '../x' }, { match_id: 'a b' }, { match_id: 'abc123' }, { match_id: '' }] }],
  });
  assert.deepEqual(tableIds(live), ['abc123']);
});

test('the status banner says what is true for each status', () => {
  assert.match(statusBanner(normalizeLive({ status: 'idle' })).text, /Waiting for players/);
  const starting = statusBanner(normalizeLive({ status: 'starting', delay_seconds: 360 }));
  assert.match(starting.text, /Play appears on this page shortly/);
  assert.match(starting.text, /about 6 minutes behind/);
  const running = statusBanner(
    normalizeLive({
      status: 'running',
      round: 1,
      rounds: [
        {
          round: 1,
          tables: [
            { match_id: 'a', players: ['p', 'q', 'r', 's'], status: 'playing', eliminated: ['s'] },
            { match_id: 'b', players: ['t', 'u'], status: 'finished' },
          ],
        },
      ],
    }),
  );
  assert.equal(running.label, 'Round 1');
  assert.match(running.text, /Round 1 is in progress/);
  assert.match(running.text, /1 table playing of 2/);
  assert.match(running.text, /5 players still in/);
  const final = statusBanner(normalizeLive({ status: 'running', round: 2, rounds: [{ round: 2, tables: [{ match_id: 'a', players: ['p', 'q'], status: 'playing' }] }] }));
  assert.equal(final.label, 'Final');
  assert.match(final.text, /final table is playing/);
  assert.match(statusBanner(finished).text, /champion is device-5-1793998903/);
  assert.equal(statusBanner(normalizeLive({ status: 'finished' })).text, 'The tournament is over.');
});

test('tables are labelled, the lone table of a later round is the final', () => {
  const all = allTables(finished);
  assert.deepEqual(
    all.map((x) => x.label),
    ['Table 1', 'Table 2', 'Table 3', 'Final table'],
  );
  assert.deepEqual(
    all.map((x) => x.round),
    [1, 1, 1, 2],
  );
});

test('table cards: players with chips and a state in words', () => {
  const final = allTables(finished)[3].table;
  const players = tablePlayers(final);
  assert.deepEqual(players.find((p) => p.name === 'device-5-1793998903'), { name: 'device-5-1793998903', chips: 600, state: 'winner' });
  assert.equal(players.find((p) => p.name === 'device-2-1793998903').state, 'out');
  assert.equal(tableStateText(final), 'finished — device-5-1793998903 won');
  assert.equal(tableStateText({ status: 'playing', winners: [] }), 'playing');
  assert.equal(tableStateText({ status: 'finished', winners: [] }), 'finished');
});

const tablesById = (spec) => Object.fromEntries(Object.entries(spec).map(([id, ends]) => [id, { hands: ends.map((end) => ({ end })) }]));
const threeTables = normalizeLive({
  rounds: [{ round: 1, tables: [{ match_id: 'a', status: 'playing' }, { match_id: 'b', status: 'playing' }, { match_id: 'c', status: 'finished' }] }],
});

test('the featured table is the one with the most recent hand; playing beats finished', () => {
  assert.equal(latestEnd({ hands: [{ end: 5 }, { end: 9 }, {}] }), 9);
  assert.equal(latestEnd({ hands: [] }), null);
  assert.equal(latestEnd(null), null);
  assert.equal(pickFeatured(threeTables, tablesById({ a: [1, 5], b: [2, 8], c: [1, 99] })), 'b');
  assert.equal(pickFeatured(threeTables, tablesById({ a: [], b: [] })), null);
  assert.equal(pickFeatured(threeTables, tablesById({ a: [3], b: [], c: [50] })), 'a');
  assert.equal(pickFeatured(threeTables, {}), null);
  const allDone = normalizeLive({ rounds: [{ round: 1, tables: [{ match_id: 'a', status: 'finished' }, { match_id: 'b', status: 'finished' }] }] });
  assert.equal(pickFeatured(allDone, tablesById({ a: [4], b: [7] })), 'b');
});

test('the shown table is kept, a visitor choice wins, and a watched-out table moves on', () => {
  const tables = tablesById({ a: [1, 5], b: [2, 8], c: [1, 99] });
  assert.equal(chooseShown(threeTables, tables, { current: 'a' }), 'a');
  assert.equal(chooseShown(threeTables, tables, { current: 'a', choice: 'c' }), 'c');
  assert.equal(chooseShown(threeTables, tables, { choice: 'gone', current: 'gone' }), 'b');
  // 'c' has finished: once its playback reached the end, move on; never back to it.
  assert.equal(chooseShown(threeTables, tables, { current: 'c', finishedAndSeen: () => false }), 'c');
  assert.equal(chooseShown(threeTables, tables, { current: 'c', finishedAndSeen: (id) => id === 'c' }), 'b');
  // Everything finished and watched: stay where it is.
  const over = normalizeLive({ rounds: [{ round: 1, tables: [{ match_id: 'a', status: 'finished' }, { match_id: 'c', status: 'finished' }] }] });
  assert.equal(chooseShown(over, tables, { current: 'c', finishedAndSeen: () => true }), 'c');
});

test('status line under the table and the words on a seat', () => {
  assert.match(playbackStatus({ state: 'waiting', delay: 360 }), /Waiting for the next update/);
  assert.equal(playbackStatus({ state: 'finished', winners: ['x'] }), 'This table has finished: x won.');
  assert.equal(playbackStatus({ state: 'paused', behind: 2 }), 'Paused · 2 hands behind the live edge');
  assert.equal(playbackStatus({ state: 'playing', behind: 0 }), 'Playing · at the live edge of the feed');
  assert.match(playbackStatus({ state: 'playing', behind: 9, catchUp: 4 }), /9 hands behind the live edge \(catching up, 4\.0×\)/);
  assert.match(playbackStatus({ state: 'empty' }), /No hands are visible/);
  assert.deepEqual(seatStatus({ winner: true, winnings: 1500, state: 'in', bet: 0 }), { text: 'wins 1,500', bet: 0 });
  assert.equal(seatStatus({ state: 'folded', bet: 20 }).text, 'folded');
  assert.equal(seatStatus({ state: 'allin', bet: 20 }).bet, 20);
  assert.equal(seatStatus({ state: 'in', bet: 0, note: 'checks' }, true).text, 'to act');
  assert.equal(seatStatus({ state: 'in', bet: 0, note: 'checks' }).text, 'checks');
  assert.equal(seatStatus({ state: 'out', note: 'eliminated', bet: 0 }).text, 'eliminated');
  assert.equal(seatStatus({ state: 'in', hole: ['AS', 'KD'], hand: 'Pair', bet: 0 }).text, 'Pair');
});

test('team badges and the summary are words', () => {
  assert.equal(teamBadge('champion').text, 'champion');
  assert.equal(teamBadge('out').text, 'out');
  assert.equal(teamBadge('???').cls, 'badge');
  assert.equal(teamSummary([{ status: 'out' }, { status: 'playing' }, { status: 'out' }, { status: 'registered' }]), '1 registered, 1 playing, 2 out');
  assert.equal(teamSummary([]), '');
});
