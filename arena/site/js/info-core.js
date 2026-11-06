// The Info page's logic: the "Connect now" values and the commands built from
// them. Pure (no DOM), tested in Node (tests/site_js/info-core.test.mjs).
//
// The server address, the join code, the form link and the note come from the
// data (info.json), so they are untrusted: they are shown as text, and every
// value put into a command is quoted so a copied command cannot run anything
// else. Nothing is fetched from them.

import { delayText, intervalText } from './live-core.js';

export const SERVER_PLACEHOLDER = '<server-address>';
export const CODE_PLACEHOLDER = 'YOUR-CODE';
export const TEAM_PLACEHOLDER = 'YOUR-TEAM-NAME';
export const KEY_PLACEHOLDER = '<your key>';
export const NO_SERVER = 'The organiser will announce the server address.';
export const NO_CODE = 'Ask the organiser for the join code.';

const CONTROL = /[\u0000-\u001f\u007f]/g;
const PLAIN = /^[A-Za-z0-9_.:/@%+=,-]+$/;

/** A value with control characters (and so newlines) taken out. */
export function clean(value) {
  return typeof value === 'string' ? value.replace(CONTROL, '').trim() : '';
}

/** `value` as one POSIX shell word: bare when plain, else single-quoted. */
export function shellWord(value) {
  const v = clean(value);
  if (PLAIN.test(v)) return v;
  return `'${v.replace(/'/g, "'\\''")}'`;
}

/** `value` as one PowerShell string: single-quoted, quotes doubled. */
export function powershellString(value) {
  return `'${clean(value).replace(/'/g, "''")}'`;
}

/** The server address without a trailing slash, or null. */
export function serverBase(info) {
  const v = clean(info && info.server_url);
  return v ? v.replace(/\/+$/, '') : null;
}

/** A link worth making clickable: only http or https addresses, else null. */
export function safeHref(value) {
  const v = clean(value);
  if (!v) return null;
  try {
    const url = new URL(v);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

/**
 * Everything the "Connect now" card shows:
 *   {server, code, hasServer, hasCode, serverLine, codeLine,
 *    commands: {register: {bash, powershell}, run}}
 * With no server address the commands carry a visible placeholder; with no
 * join code they carry YOUR-CODE.
 */
export function connectInfo(info) {
  const base = serverBase(info);
  const code = clean(info && info.join_code) || null;
  const server = base || SERVER_PLACEHOLDER;
  const registerUrl = `${server}/v1/register`;
  const body = `{"player_id": ${JSON.stringify(TEAM_PLACEHOLDER)}, "code": ${JSON.stringify(code || CODE_PLACEHOLDER)}}`;
  return {
    server: base,
    code,
    hasServer: Boolean(base),
    hasCode: Boolean(code),
    serverLine: base || NO_SERVER,
    codeLine: code || NO_CODE,
    commands: {
      register: {
        bash: `curl -X POST ${base ? shellWord(registerUrl) : registerUrl} -H 'Content-Type: application/json' -d ${shellWord(body)}`,
        powershell: `Invoke-RestMethod -Method Post -Uri ${base ? powershellString(registerUrl) : `'${registerUrl}'`} -ContentType 'application/json' -Body ${powershellString(body)}`,
      },
      run: `python -m player_sdk my_bot.py --tournament --server-url ${base ? shellWord(base) : server} --api-key ${KEY_PLACEHOLDER}`,
    },
  };
}

/** The paragraphs of "How this site works", from the delay and update interval. */
export function howItWorks(info, manifest = null) {
  const seconds = info && Number.isFinite(info.delay_seconds) ? info.delay_seconds : manifest && Number.isFinite(manifest.delay_seconds) ? manifest.delay_seconds : null;
  const delay = delayText(seconds);
  const every = intervalText(info && info.interval_seconds);
  return [
    `This site shows the game ${delay ? `${delay} behind` : 'behind'} the real one. A hand appears here only once it finished that long ago, so nobody can use the site to see what is happening at the tables right now.`,
    `The site is updated ${every || 'every few minutes'}. Between updates it replays the new hands at a pace you can follow, so the speed on screen is not the speed of the game.`,
    'Shown: every table with its players, chips, actions, board and pot. Hole cards are shown only when a hand reaches a showdown, and only for the players who reach it. Cards of players who fold are never shown.',
    'Not shown: anything that is still happening, and any hand that finished less than the delay ago.',
  ];
}
