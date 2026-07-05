# AGENTS.md — Published branch guard

This `main` branch is generated from the canonical `developer` branch.

- Do not implement or hand-edit fixes on `main`; switch to `developer`, test there, and regenerate the published tree.
- Before any push, tag push, remote branch/tag creation or deletion, force push, PR creation, or GitHub Release, report the remote and commit range and obtain the user's explicit approval for that remote action.
- Approval to edit, test, or commit locally is not approval to push.
- Force push is prohibited unless the user explicitly names and approves that operation after the risk is explained.
