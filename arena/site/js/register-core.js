// The checks behind the Register page, and the pre-filled GitHub link it
// opens. Pure (no DOM), tested in Node. The rules mirror the arena's own
// (arena/registry.py), so a registration that passes here is not turned away
// for its format later; the arena still checks everything again.

export const TEAM_NAME = /^[a-z0-9][a-z0-9_-]{0,31}$/;
export const BRANCH = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$/;
export const GITHUB_REPO = /^https:\/\/github\.com\/([A-Za-z0-9-]+)\/([\w.-]+?)(?:\.git)?\/?$/;

const ok = (value, extra = {}) => ({ ok: true, value, message: '', ...extra });
const bad = (message, value = '') => ({ ok: false, value, message });

/** Team names are lowercase; typing capitals is fixed for you, not refused. */
export function validateTeam(raw) {
  const value = String(raw ?? '').trim().toLowerCase();
  if (!value) return bad('Enter a team name.');
  if (value.length > 32) return bad('Use at most 32 characters.', value);
  if (!TEAM_NAME.test(value)) {
    return bad(
      'Use only letters, digits, “-” and “_”, starting with a letter or digit.',
      value,
    );
  }
  return ok(value);
}

export function validateRepo(raw) {
  const value = String(raw ?? '').trim();
  if (!value) return bad('Enter the address of your GitHub repository.');
  if (/^https:\/\/[^/]*@/i.test(value)) {
    return bad('Remove the password or token from the address.', value);
  }
  const match = GITHUB_REPO.exec(value);
  if (!match) {
    return bad(
      'Use the address of a public GitHub repository, like https://github.com/your-name/your-bot.',
      value,
    );
  }
  return ok(value, { owner: match[1], name: match[2] });
}

export function validateBranch(raw) {
  const value = String(raw ?? '').trim();
  if (!value) return ok('');
  if (!BRANCH.test(value)) return bad('That is not a usable branch name.', value);
  return ok(value);
}

/** The link that opens the registration form in the registry, filled in. */
export function buildIssueUrl(registry, { team, repo, branch }) {
  const query = new URLSearchParams({
    template: 'register.yml',
    title: `Register: ${team}`,
    team,
    repo,
  });
  if (branch) query.set('branch', branch);
  return `https://github.com/${registry}/issues/new?${query.toString()}`;
}

/** Where a team can watch the status of its registration. */
export function registryIssuesUrl(registry) {
  return `https://github.com/${registry}/issues`;
}

/** What the form currently says, ready for the page to show. */
export function checkForm({ team, repo, branch }) {
  const t = validateTeam(team);
  const r = validateRepo(repo);
  const b = validateBranch(branch);
  return { team: t, repo: r, branch: b, ready: t.ok && r.ok && b.ok };
}
