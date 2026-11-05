// Where the Register page sends a team. Pure (no DOM), tested in Node.
//
// The registration form itself lives on GitHub (the registry's issue form),
// which asks for the team name, repository and branch and checks them; the
// arena then checks them again and replies on the issue.

const REGISTRY = /^[\w.-]+\/[\w.-]+$/;

/** The registry's registration form, or null if the name is not OWNER/REPO. */
export function registerUrl(registry) {
  if (!REGISTRY.test(String(registry ?? ''))) return null;
  return `https://github.com/${registry}/issues/new?template=register.yml`;
}

/** Where a team can watch the status of its registration. */
export function registryIssuesUrl(registry) {
  if (!REGISTRY.test(String(registry ?? ''))) return null;
  return `https://github.com/${registry}/issues`;
}
