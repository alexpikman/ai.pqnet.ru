# Repository contribution rules

## Branch policy — mandatory
- Work directly on `main` only.
- Never create, switch to, push to, or update a feature, fix, test, release, or other non-`main` branch.
- Never create pull requests for routine project changes. Commit changes directly to `main`.
- Before editing, fetch/read the current file from `main` and preserve unrelated changes.
- For multi-file changes, make sequential commits on `main`; do not use an old branch snapshot to replace a newer file wholesale.
- Do not delete any branch until its unique changes have been reviewed and either merged into `main` or explicitly determined obsolete.
- After changes, verify the resulting `main` ref and run the available tests/CI where possible.
