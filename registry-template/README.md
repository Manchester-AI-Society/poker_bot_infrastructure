# Registry repository (organiser setup)

Teams register by opening an issue in this repository. The arena reads the
issues, checks that the issue's author owns the repository they name, and, once
you approve, fetches and plays that repository's `bot.py`.

## Set up (once)

1. Create a **public** repository, for example `your-org/poker-registry`
   (public so teams can open issues without being added, and so the Register
   page can show what is waiting).
2. Copy the `.github/` folder from this directory into it and push.
   If the registry is an existing repository that also takes ordinary issues,
   copy only `register.yml`: `config.yml` turns blank issues off for the whole
   repository. GitHub reads issue forms from the **default branch** only.
3. Create these labels in the repository (Issues -> Labels):
   - `registration`  - added automatically by the form
   - `approved`      - you add this to let a team in
   - `verified`      - you add this to accept a repository owned by a
     different account than the issue's author (for example a team
     organisation); use sparingly

## Run the arena against it

    python -m arena sync   --registry your-org/poker-registry
    python -m arena ladder --registry your-org/poker-registry --teams teams.txt
    python -m arena export --registry-repo your-org/poker-registry ...

Use `--open-registration` to skip approval (only for a private, trusted
event: a registered repository's code runs on your machine, unsandboxed).

The arena replies on each issue once per outcome (accepted, waiting for
approval, or why it was refused). `gh` must be signed in (or set
`GITHUB_TOKEN`) so it can read and comment.

## Rules the arena applies

- The issue author must own the repository (or the issue has `verified`).
- One team per GitHub account (`--max-per-user` raises this); one team per
  repository; team names are first come, first served.
- A newer issue from the same account replaces its older one; closing an
  issue withdraws the registration.
