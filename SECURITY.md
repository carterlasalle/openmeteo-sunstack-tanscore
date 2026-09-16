# Security Policy

## Supported versions

Security fixes go to `main` only, via normal pull requests. There are no
maintained release branches; the scheduled forecast pipeline always runs the
tip of `main`.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private vulnerability reporting
(Security tab → Report a vulnerability) so the fix can land before details
are public.

Include: what you found, which file or workflow is affected, and a minimal
reproduction. You will get a response as soon as the report is reviewed —
this is a solo-maintained project, so allow a few days.

## Secrets and credentials

This repository's threat surface is almost entirely credential leakage, not
application exploits. The rules:

- Never commit `~/.cdsapirc` contents, API tokens, PATs, scheduler keys, or
  provider responses containing credentials — in code, issues, PRs, logs, or
  artifacts.
- The scheduled workflow needs only `contents: write`. Do not widen it.
- The external scheduler stores a fine-grained PAT limited to this repo's
  Actions (read/write). Its response saving is disabled so the token never
  lands in execution history.
- If any credential is exposed (chat log, commit, screenshot, response body):
  **revoke it immediately**, then rotate dependents (cron-job key and GitHub
  PAT are paired — rotate both).

## Scope notes

- Strict mode is a correctness gate, not a security boundary: it refuses to
  publish on missing/failed sources rather than scoring blind.
- TanScore is an environmental model, not exposure advice; see the
  interpretation note in [README.md](README.md).
- Dependency updates arrive via Dependabot; CI must stay green before merge.
