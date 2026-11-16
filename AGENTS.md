# Contributor instructions

- Write code, comments, documentation, issues and commits in English.
- Never merge pull requests unless the user explicitly authorizes a merge.
- Never add Co-authored-by commit trailers.
- Keep Plesk-specific behavior here and generic application behavior in Tabularis core.
- Do not commit credentials, cookies, keys, database dumps or runtime state.
- Tabularis and the HTTP gateway must run as unprivileged, separate Unix users.
- Every browser request must be authorized against the effective Plesk session. URLs are never access grants.
- Fail closed on unsupported permissions, stale catalogues or partial reconciliation.
- Test authorization boundaries, both MySQL/MariaDB and PostgreSQL, and packaging before opening a PR.
- Run `python3 -m unittest discover -s tests -v`, PHP syntax checks and `python3 scripts/package.py`.
- Use the real Plesk lab for SDK and database privilege assertions; document unverified cases explicitly.
