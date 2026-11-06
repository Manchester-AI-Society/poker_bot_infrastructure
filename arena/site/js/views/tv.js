// TV mode: a hands-off rotation for a projector. Each slide is built fresh
// from the current data when its turn comes, so it stays up to date without
// the page being re-rendered.

import { allPairings } from '../api.js';
import { h } from '../dom.js';
import { replayView } from './replay.js';
import { leaderboardTable, kindBadge, emptyBoard } from './leaderboard.js';
import { matchRow } from './matches.js';
import { matrixGrid } from './matrix.js';
import { finalsStage, advanceText, isTournament, phaseInfo, revealedBoards } from '../tournament-core.js';
import { championBanner, finalsSection, groupCard, phaseBanner, roundOneSection } from './tournament.js';

const SLIDE_SECONDS = 14;
const REPLAY_SECONDS = 30;

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

/** The head-to-head grid sized so every team fits the screen, whatever the count. */
function matrixCard(board) {
  const n = board.teams.length;
  const byHeight = Math.floor((window.innerHeight - 360) / (n + 2.5));
  const byWidth = Math.floor((window.innerWidth - 320) / (n + 1));
  const cellPx = Math.max(16, Math.min(56, byHeight, byWidth));
  const { grid, legend } = matrixGrid(board, {
    numbers: n <= 10,
    cellPx,
  });
  return h('div', { class: 'card' }, grid, legend);
}

export function tvView(ctx) {
  const wrap = h('div', { class: 'tvwrap' });
  const title = h('h1', {});
  const dots = h('div', { class: 'tvdots', 'aria-hidden': 'true' });
  const bar = h('i', {});
  const body = h('div', { class: 'tvbody' });
  const exit = h('a', { class: 'tvexit', href: '#/' }, 'Exit TV mode (Esc)');
  wrap.append(
    h('div', { class: 'tvhead' }, title, dots),
    h('div', { class: 'tvbar' }, bar),
    body,
    exit,
  );
  document.documentElement.classList.add('tv');

  let index = 0;
  let timer = null;
  let paused = false;
  let child = null;
  let showToken = 0;
  const tournament = isTournament(ctx.data.manifest);

  // Shared by both formats: the newest results and a hand to watch.
  const sharedSlides = () => [
    {
      name: 'Latest results',
      build() {
        const list = allPairings().slice(0, 6);
        if (!list.length) return null;
        const now = Date.now();
        return h('div', { class: 'card' }, h('ul', { class: 'mlist' }, list.map((p) => matchRow(p, now))));
      },
    },
    {
      name: 'A hand to watch',
      seconds: REPLAY_SECONDS,
      async build() {
        const withReplay = allPairings().filter((p) => p.replay);
        if (!withReplay.length) return null;
        const pairing = pick(withReplay);
        const view = await replayView(
          { path: ['replay', pairing.id, String(Math.floor(Math.random() * 20))], data: ctx.data, kind: ctx.kind, query: {} },
          { compact: true, autoplay: true, onFinish: () => next() },
        );
        child = view;
        return h('div', {}, h('p', { class: 'muted' }, `${pairing.a} vs ${pairing.b}`), view.el);
      },
    },
  ];

  const ladderSlides = () => [
    {
      name: 'Leaderboard',
      build() {
        const board = ctx.data.boards[ctx.kind];
        if (!board || !board.teams.length) return emptyBoard(ctx.kind);
        return h('div', { class: 'card' }, leaderboardTable(board, { limit: 10 }));
      },
    },
    {
      name: 'Head-to-head',
      build() {
        const board = ctx.data.boards[ctx.kind];
        if (!board || board.teams.length < 2) return null;
        return matrixCard(board);
      },
    },
    ...sharedSlides(),
  ];

  /** Slides for the tournament: what exists, and nothing that is not published. */
  const tournamentSlides = () => {
    const t = ctx.data.tournament;
    const boards = revealedBoards(t, ctx.data.boards.final);
    return [
      {
        name: 'Tournament',
        build() {
          return h(
            'div',
            { class: 'tvstatus' },
            phaseBanner(t),
            championBanner(t),
            t.rounds !== 1 && finalsStage(t) === 'unknown' ? h('p', { class: 'note' }, advanceText(t.advance)) : null,
          );
        },
      },
      {
        name: t.rounds === 1 ? 'The round' : 'Round 1: groups',
        build() {
          // Before the reveal: the draw. After it, each group has its own slide.
          return boards.some((b) => b.kind === 'group') || !t.groups.length ? null : roundOneSection(t);
        },
      },
      ...t.groups
        .filter((g) => g.board)
        .map((g) => ({
          name: `Group ${g.name}`,
          build: () => groupCard(g, t),
        })),
      {
        name: 'Finals',
        build() {
          return t.rounds === 1 || finalsStage(t) === 'unknown' ? null : finalsSection(t, ctx.data.boards.final);
        },
      },
      ...boards.map((b) => ({
        name: `Head-to-head: ${b.label}`,
        build: () => (b.board.teams.length < 2 ? null : matrixCard(b.board)),
      })),
      ...sharedSlides(),
    ];
  };

  const buildSlides = () => (tournament ? tournamentSlides() : ladderSlides());
  let slides = [];

  async function show(position) {
    const mine = ++showToken;
    clearTimeout(timer);
    slides = buildSlides(); // the data may have changed since the last slide
    if (child && child.dispose) child.dispose();
    child = null;
    // Skip slides with nothing to show (for example no replays published).
    for (let tries = 0; tries < slides.length; tries += 1) {
      index = ((position % slides.length) + slides.length) % slides.length;
      const slide = slides[index];
      const content = await slide.build();
      if (mine !== showToken) {
        // A newer slide was requested while this one was loading.
        if (slide.name === 'A hand to watch' && child && child.dispose) child.dispose();
        return;
      }
      if (content) {
        title.replaceChildren(
          slide.name,
          ' ',
          tournament ? h('span', { class: 'badge' }, phaseInfo(ctx.data.tournament.phase).label) : kindBadge(ctx.kind),
        );
        body.replaceChildren(content);
        dots.replaceChildren(...slides.map((_, i) => h('span', { class: i === index ? 'on' : '' })));
        const seconds = slide.seconds || SLIDE_SECONDS;
        bar.style.transition = 'none';
        bar.style.width = '0';
        void bar.offsetWidth; // restart the CSS transition
        bar.style.transition = `width ${seconds}s linear`;
        bar.style.width = '100%';
        if (!paused) timer = setTimeout(next, seconds * 1000);
        return;
      }
      position += 1;
    }
    body.replaceChildren(h('p', { class: 'empty' }, 'Nothing to show yet.'));
  }

  function next() { show(index + 1); }
  function prev() { show(index - 1); }

  function onKey(event) {
    if (event.key === 'Escape') location.hash = '#/';
    else if (event.key === 'ArrowRight') next();
    else if (event.key === 'ArrowLeft') prev();
    else if (event.key === ' ') {
      event.preventDefault();
      paused = !paused;
      if (paused) {
        clearTimeout(timer);
        bar.style.transition = 'none';
      } else show(index);
    }
  }
  document.addEventListener('keydown', onKey);
  show(0);

  return {
    el: wrap,
    title: 'TV mode',
    dispose() {
      clearTimeout(timer);
      if (child && child.dispose) child.dispose();
      document.removeEventListener('keydown', onKey);
      document.documentElement.classList.remove('tv');
    },
  };
}
