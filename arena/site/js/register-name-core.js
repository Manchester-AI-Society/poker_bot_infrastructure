// The Register page's logic for a tournament: is this a usable team name, is
// it already listed, and where does the registration form take it. Pure (no
// DOM), tested in Node (tests/site_js/register-name-core.test.mjs).
//
// The rule is the arena's own team-name rule (arena/roster.py TEAM_NAME), so
// a name this page accepts is one the exporter will list.

import { entryStatus } from './tournament-core.js';

export const MAX_NAME_LENGTH = 32;

const NAME = /^[a-z0-9][a-z0-9_-]{0,31}$/;

/** What a visitor typed, as the arena will read it: trimmed and lowercase. */
export function foldName(raw) {
  return String(raw ?? '').trim().toLowerCase();
}

/** Characters of `name` that a team name may not contain, each listed once. */
function badCharacters(name) {
  const seen = [];
  for (const ch of name) {
    if (!/[a-z0-9_-]/.test(ch) && !seen.includes(ch)) seen.push(ch);
  }
  return seen;
}

const shown = (ch) => (ch === ' ' ? 'a space' : `“${ch}”`);

/**
 * Checks a typed name. Returns {state, name, message}:
 *   state 'empty'    nothing typed yet (message is '', so nothing is said)
 *   state 'invalid'  message says what is wrong, in words
 *   state 'valid'    `name` is the folded, valid name
 * `name` is always the folded text, so the page can show what will be used.
 */
export function checkName(raw) {
  const name = foldName(raw);
  if (!name) return { state: 'empty', name, message: '' };
  if (name.length > MAX_NAME_LENGTH) {
    return {
      state: 'invalid',
      name,
      message: `That is ${name.length} characters; a team name is at most ${MAX_NAME_LENGTH}.`,
    };
  }
  const bad = badCharacters(name);
  if (bad.length) {
    return {
      state: 'invalid',
      name,
      message: `Only lowercase letters, digits, “-” and “_” are allowed. Not allowed here: ${bad.map(shown).join(', ')}.`,
    };
  }
  if (!NAME.test(name)) {
    return { state: 'invalid', name, message: 'A team name must start with a letter or a digit.' };
  }
  return { state: 'valid', name, message: '' };
}

/** True when `name` (already folded) is a valid team name. */
export function isValidName(name) {
  return NAME.test(String(name ?? ''));
}

/**
 * The registration form's address, if it is one this site should send people
 * to: a Google Forms link over https, no spaces, ending in "=" so the team
 * name can be appended. Anything else gives null.
 */
export function formAddress(form) {
  if (typeof form !== 'string' || !form.endsWith('=') || /\s/.test(form)) return null;
  let url;
  try {
    url = new URL(form);
  } catch {
    return null;
  }
  const ok =
    url.protocol === 'https:' &&
    url.hostname === 'docs.google.com' &&
    url.port === '' &&
    url.username === '' &&
    url.password === '' &&
    url.pathname.startsWith('/forms/');
  return ok ? form : null;
}

/**
 * The link that opens the registration form with `raw` filled in, or null
 * when the name is not valid or the form address is missing or unusable.
 * The name is encoded, so it can only ever be the value of that one entry.
 */
export function registerLink(form, raw) {
  const address = formAddress(form);
  if (!address) return null;
  const checked = checkName(raw);
  if (checked.state !== 'valid') return null;
  return address + encodeURIComponent(checked.name);
}

/** The listed team with this (folded) name, as {team, status}, or null. */
export function listedTeam(teams, raw) {
  const name = foldName(raw);
  const entry = (teams || []).find((t) => t.team === name);
  return entry ? { team: entry.team, status: entryStatus(entry) } : null;
}

/**
 * Everything the Register page needs for what is typed:
 *   {check, listed, link, message}
 * `link` is non-null only for a valid name that is not listed yet, and
 * `message` is the one line to show under the field.
 */
export function registerState(form, teams, raw) {
  const check = checkName(raw);
  const listed = check.state === 'valid' ? listedTeam(teams, check.name) : null;
  let message = check.message;
  if (listed) {
    message = `This name is already listed (${listed.status}). Choose another name.`;
  }
  const link = check.state === 'valid' && !listed ? registerLink(form, check.name) : null;
  if (check.state === 'valid' && !listed) {
    message = link
      ? `“${check.name}” is not listed yet. You can register it.`
      : 'The registration form address is missing or not usable. Ask the organiser.';
  }
  return { check, listed, link, message };
}
