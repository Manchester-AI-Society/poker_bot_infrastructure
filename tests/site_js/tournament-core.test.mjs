import test from 'node:test';
import assert from 'node:assert/strict';
import {
  NOT_YET,
  PHASE_ORDER,
  advanceText,
  finalMarks,
  finalsNote,
  finalsStage,
  groupMarks,
  groupsRevealed,
  isTournament,
  normalizeTournament,
  phaseInfo,
  qualifiedInGroup,
  revealedBoards,
  roundOneNote,
  teamStanding,
  tournamentFiles,
  updatedText,
} from '../../arena/site/js/tournament-core.js';

const row = (team, rank, score = 0.1) => ({ team, rank, score, ci95: 0.2, wins: 1, draws: 0, losses: 0 });
const board = (...names) => ({ kind: 'group', teams: names.map((n, i) => row(n, i + 1, 1 - i / 10)), matrix: {} });

/** The shape the exporter writes for each phase (20 teams in the real data; 5 here). */
function sample(phase) {
  const drawn = [
    { name: 'A', teams: ['a1', 'a2', 'a3'] },
    { name: 'B', teams: ['b1', 'b2'] },
  ];
  const groups = (withBoards) =>
    drawn.map((g) => ({
      ...g,
      board: withBoards ? board(...[...g.teams].reverse()) : null,
    }));
  const base = { phase, advance: 2, groups: [], qualified: [], finals: null, champion: null };
  switch (phase) {
    case 'registration':
      return base;
    case 'drawn':
    case 'groups':
      return { ...base, groups: groups(false) };
    case 'between':
      return { ...base, groups: groups(true), qualified: ['a3', 'a2', 'b2', 'b1'] };
    case 'finals':
      return {
        ...base,
        groups: groups(true),
        qualified: ['a3', 'a2', 'b2', 'b1'],
        finals: { teams: ['a3', 'a2', 'b2', 'b1'], board: null },
      };
    default:
      return {
        ...base,
        groups: groups(true),
        qualified: ['a3', 'a2', 'b2', 'b1'],
        finals: { teams: ['a3', 'a2', 'b2', 'b1'], board: board('b2', 'a3', 'a2', 'b1') },
        champion: 'b2',
      };
  }
}

test('every phase has a plain-words banner', () => {
  assert.deepEqual(PHASE_ORDER, ['registration', 'drawn', 'groups', 'between', 'finals', 'done']);
  const texts = PHASE_ORDER.map((p) => phaseInfo(p));
  for (const info of texts) {
    assert.ok(info.known);
    assert.ok(info.label && info.text.endsWith('.'), info.phase);
  }
  assert.match(phaseInfo('registration').text, /signing up/);
  assert.match(phaseInfo('drawn').text, /drawn/);
  assert.match(phaseInfo('drawn').text, /not started/);
  assert.match(phaseInfo('groups').text, /Round 1.*in progress.*when the round ends/);
  assert.match(phaseInfo('between').text, /Round 1 is complete.*finals are about to start/);
  assert.match(phaseInfo('finals').text, /finals are in progress.*when the round ends/);
  assert.match(phaseInfo('done').text, /finished/);
  assert.equal(new Set(texts.map((i) => i.text)).size, 6);
});

test('an unknown or missing phase still reads sensibly', () => {
  for (const phase of ['', undefined, null, 'warmup']) {
    const info = phaseInfo(phase);
    assert.equal(info.known, false);
    assert.ok(info.text.length > 0);
  }
});

test('mode detection follows the manifest only', () => {
  assert.equal(isTournament({ mode: 'tournament' }), true);
  assert.equal(isTournament({ mode: 'ladder' }), false);
  assert.equal(isTournament({}), false); // a legacy manifest has no mode
  assert.equal(isTournament(null), false);
});

test('normalizing tolerates missing and null parts', () => {
  for (const raw of [null, undefined, {}, { groups: null, finals: null }, 'x']) {
    const t = normalizeTournament(raw);
    assert.deepEqual(t.groups, []);
    assert.deepEqual(t.qualified, []);
    assert.equal(t.finals, null);
    assert.equal(t.champion, null);
    assert.equal(t.advance, 2);
  }
  const t = normalizeTournament({
    advance: 1,
    groups: [{ name: 'A', teams: null, board: { teams: 'nope' } }, { name: 'B', teams: ['x'], board: null }],
    qualified: null,
    finals: { teams: ['x'], board: null },
  });
  assert.equal(t.advance, 1);
  assert.deepEqual(t.groups[0], { name: 'A', teams: [], board: null });
  assert.deepEqual(t.finals, { teams: ['x'], board: null });
  assert.equal(normalizeTournament({ advance: 0 }).advance, 2);
  assert.equal(normalizeTournament({ advance: 'x' }).advance, 2);
});

test('only files the manifest lists are requested', () => {
  const none = tournamentFiles({ mode: 'tournament', kinds: [] });
  assert.equal(none.tournament, 'data/tournament.json');
  assert.equal(none.teams, 'data/teams.json');
  assert.deepEqual(none.pairings, {});
  assert.deepEqual(none.boards, {});

  const groupsOnly = tournamentFiles({ kinds: ['group'] });
  assert.deepEqual(groupsOnly.pairings, { group: 'data/pairings-group.json' });
  assert.deepEqual(groupsOnly.boards, {}); // there is no leaderboard-group.json

  const both = tournamentFiles({ kinds: ['group', 'final'] });
  assert.deepEqual(both.pairings, {
    group: 'data/pairings-group.json',
    final: 'data/pairings-final.json',
  });
  assert.deepEqual(both.boards, { final: 'data/leaderboard-final.json' });

  // A manifest with no kinds field, or an unknown kind, requests nothing extra.
  assert.deepEqual(tournamentFiles({}).pairings, {});
  assert.deepEqual(tournamentFiles({ kinds: ['ladder'] }).pairings, {});
});

test('before the draw there is nothing to show', () => {
  const t = normalizeTournament(sample('registration'));
  assert.equal(groupsRevealed(t), false);
  assert.deepEqual(revealedBoards(t), []);
  assert.equal(finalsStage(t), 'unknown');
  assert.match(roundOneNote(t), /drawn when registration closes/);
});

test('drawn and groups phases show the draw but no results', () => {
  for (const phase of ['drawn', 'groups']) {
    const t = normalizeTournament(sample(phase));
    assert.equal(groupsRevealed(t), false, phase);
    assert.deepEqual(revealedBoards(t), [], phase);
    assert.ok(roundOneNote(t).includes(NOT_YET), phase);
    assert.equal(finalsStage(t), 'unknown', phase);
    assert.equal(qualifiedInGroup(t.groups[0], t).size, 0, phase);
    assert.equal(groupMarks(t.groups[0], t).size, 0, phase);
    assert.equal(finalMarks(t).size, 0, phase);
  }
  assert.match(roundOneNote(normalizeTournament(sample('drawn'))), /has not started/);
  assert.match(roundOneNote(normalizeTournament(sample('groups'))), /in progress/);
});

test('between rounds the groups are revealed and the finalists are known', () => {
  const t = normalizeTournament(sample('between'));
  assert.equal(groupsRevealed(t), true);
  assert.equal(roundOneNote(t), null);
  assert.deepEqual(revealedBoards(t).map((b) => b.label), ['Group A', 'Group B']);
  assert.equal(finalsStage(t), 'known');
  assert.match(finalsNote(t), /best 2 of each group.*about to start/);
  assert.ok(finalsNote(t).includes(NOT_YET));
});

test('finals in progress show the finalists but no table', () => {
  const t = normalizeTournament(sample('finals'));
  assert.equal(finalsStage(t), 'playing');
  assert.ok(finalsNote(t).includes(NOT_YET));
  assert.deepEqual(revealedBoards(t).map((b) => b.id), ['A', 'B']);
  assert.equal(finalMarks(t).size, 0);
});

test('when done the finals board and the champion are there', () => {
  const t = normalizeTournament(sample('done'));
  assert.equal(finalsStage(t), 'result');
  assert.equal(finalsNote(t), null);
  assert.deepEqual(revealedBoards(t).map((b) => b.id), ['A', 'B', 'final']);
  assert.equal(revealedBoards(t).at(-1).label, 'Finals');
  assert.deepEqual([...finalMarks(t)], [['b2', 'Champion']]);
});

test('a separately loaded final board wins over the copy in tournament.json', () => {
  const t = normalizeTournament(sample('done'));
  const other = board('x', 'y');
  assert.equal(revealedBoards(t, other).at(-1).board, other);
  const early = normalizeTournament(sample('between'));
  assert.equal(revealedBoards(early, other).at(-1).id, 'final');
});

test('the exporter list decides who is marked qualified', () => {
  const t = normalizeTournament(sample('between'));
  // Group A is ranked a3, a2, a1; group B b2, b1.
  assert.deepEqual([...qualifiedInGroup(t.groups[0], t)].sort(), ['a2', 'a3']);
  assert.deepEqual([...qualifiedInGroup(t.groups[1], t)].sort(), ['b1', 'b2']);
  assert.deepEqual([...groupMarks(t.groups[0], t)].map(([, v]) => v), ['Qualified', 'Qualified']);
  // Tie-breaks are the exporter's business: a different list is honoured.
  t.qualified = ['a1', 'b1'];
  assert.deepEqual([...qualifiedInGroup(t.groups[0], t)], ['a1']);
});

test('without a list the top advance ranked rows are marked', () => {
  for (const advance of [1, 2, 3]) {
    const t = normalizeTournament({
      advance,
      groups: [{ name: 'A', teams: ['p', 'q', 'r', 's'], board: board('p', 'q', 'r', 's') }],
    });
    assert.deepEqual([...qualifiedInGroup(t.groups[0], t)], ['p', 'q', 'r'].slice(0, advance), `advance ${advance}`);
  }
});

test('an unranked row is never marked qualified', () => {
  const t = normalizeTournament({
    advance: 2,
    groups: [
      {
        name: 'A',
        teams: ['p', 'q', 'r'],
        board: { teams: [row('p', 1), { ...row('q', 2), score: null }, { ...row('r', 3), score: null }] },
      },
    ],
  });
  assert.deepEqual([...qualifiedInGroup(t.groups[0], t)], ['p']);
});

test('a group smaller than advance marks everyone in it', () => {
  const t = normalizeTournament({
    advance: 2,
    groups: [{ name: 'A', teams: ['solo'], board: board('solo') }],
  });
  assert.deepEqual([...qualifiedInGroup(t.groups[0], t)], ['solo']);
  const empty = normalizeTournament({ advance: 2, groups: [{ name: 'E', teams: [], board: { teams: [] } }] });
  assert.equal(qualifiedInGroup(empty.groups[0], empty).size, 0);
});

test('advance wording', () => {
  assert.equal(
    advanceText(2),
    'The best 2 of each group play a round robin to decide the champion.',
  );
  assert.match(advanceText(3), /best 3 of each group/);
  assert.match(advanceText(1), /winner of each group/);
  const t = normalizeTournament({ ...sample('drawn'), advance: 1 });
  assert.match(finalsNote(t), /winner of each group.*finalists are known when Round 1 is complete/);
});

test('a team page knows the group before and the results after', () => {
  const before = teamStanding('a2', normalizeTournament(sample('groups')));
  assert.equal(before.group, 'A');
  assert.equal(before.groupSize, 3);
  assert.equal(before.groupRow, null);
  assert.equal(before.qualified, null);
  assert.equal(before.inFinals, null);
  assert.equal(before.champion, false);

  const done = normalizeTournament(sample('done'));
  const a2 = teamStanding('a2', done);
  assert.equal(a2.groupRow.rank, 2);
  assert.equal(a2.qualified, true);
  assert.equal(a2.inFinals, true);
  assert.equal(a2.finalRow.rank, 3);
  const a1 = teamStanding('a1', done);
  assert.equal(a1.qualified, false);
  assert.equal(a1.inFinals, false);
  assert.equal(a1.finalRow, null);
  assert.equal(teamStanding('b2', done).champion, true);

  const stranger = teamStanding('nobody', done);
  assert.equal(stranger.group, null);
  assert.equal(stranger.groupRow, null);
});

test('the header never claims a last result in a tournament', () => {
  const tournament = { mode: 'tournament' };
  assert.equal(updatedText(tournament, 120), 'Updated 2 min ago');
  assert.equal(updatedText(tournament, 1), 'Updated just now');
  assert.equal(
    updatedText(tournament, 600, { stale: true }),
    'Connection lost – showing data from 10 min ago',
  );
  for (const text of [updatedText(tournament, 5), updatedText(tournament, 5, { stale: true })]) {
    assert.doesNotMatch(text, /last result/i);
  }
});

test('the ladder header text is unchanged', () => {
  for (const manifest of [{ mode: 'ladder' }, {}]) {
    assert.equal(updatedText(manifest, 120), 'Last result 2 min ago');
    assert.equal(
      updatedText(manifest, 7200, { stale: true }),
      'Connection lost – showing results from 2 h ago',
    );
  }
});
