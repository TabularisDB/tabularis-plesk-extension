# Runtime installation and upgrades

Install the ZIP first, then provide a locally built, pinned Tabularis Web binary and built frontend assets. This extension does not download or execute an arbitrary latest release. Required core changes are tracked in [#1273](https://github.com/TabularisDB/tabularis/issues/1273), [#1274](https://github.com/TabularisDB/tabularis/issues/1274) and [#1572](https://github.com/TabularisDB/tabularis/issues/1572). The evaluation lab records the actual unmerged commit SHAs.

On the Plesk host as root:

```sh
apt-get install --no-install-recommends python3-aiohttp
# Put the verified binary and frontend under a root-owned, immutable-to-other-users directory.
python3 scripts/install.py \
  --binary /opt/tabularis/<commit>/tabularis \
  --sha256 <verified-binary-sha256> \
  --web-root /opt/tabularis/<commit>/web \
  --public-origin https://panel.example.test:8443
```

Use the exact browser origin, including a non-default port. If the panel is behind a reverse proxy, configure Plesk `panel.ini` `realIpFrom` narrowly and pass the matching exact proxy IP using `--trusted-panel-proxy`. That proxy must discard client-supplied forwarding headers and set a single authenticated source IP. The default trusts no forwarded IP. The gateway map and private callback preserve the same effective client IP that Plesk used at login. The HTTPS certificate remains the panel's certificate. The installer checks ownership, the binary hash, required CLI flags, frontend presence and Python dependencies before configuring its own services. It preserves existing signing keys and retains the previous configuration when settings change. Existing extension data is not overwritten by a ZIP upgrade. Restarting the broker closes active workspaces and revokes their temporary database accounts; users can reopen them from Plesk.

The panel web server includes two extension-owned configuration files: `tabularis.conf` creates a private callback Unix listener and `tabularis_plesk.inc` adds the workspace route to the existing panel. No additional public port or nested Docker daemon is used. The root broker and unprivileged gateway are supervised by systemd. Tabularis child processes run as separate `tbw_...` system users, never as root.

## Provisioning contract

The evaluation runtime is pinned to core commit `0d2a6a098f8369653b918d1e78d7f4eeeac65d8a` ([PR #1579](https://github.com/TabularisDB/tabularis/pull/1579)), including runtime base paths from #1575, mandatory proxy credentials on every protected request from #1576, provisioning hardening from #1578 and browser-only community welcome dismissal from #1579. The verified binary SHA-256 is `4f9cd68bfeeaa0dab0c293760c1e7a812528aa9c23f0c0e2c2489506b93d109a`. All prerequisite PRs remain unmerged during evaluation.

The final gateway deployment uses extension commit `ee39af503a15391cc299933f428ad8540a8cb0db` ([PR #12](https://github.com/TabularisDB/tabularis-plesk-extension/pull/12)), including permission rechecks during request-body uploads. Its ZIP SHA-256 is `3db149d7163cc4e2d1382657df13be0649871432b346b6b4384e695002d7b298`. [The lab report](../lab/VALIDATION.md) distinguishes this deployment from the unchanged UI capture revision.

The provisioning contract is pinned to core [PR #1574](https://github.com/TabularisDB/tabularis/pull/1574), commit `6cbca5bcd583c4cc591880b087a3a624d103321e`, stacked on #1573 and #1528. Provisioning requests preserve the configured public Host and never send an Origin header.

Each child receives independent `TABULARIS_WEB_PROXY_SECRET` and `TABULARIS_PROVISIONING_TOKEN` environment values. The broker uses:

- `GET /api/v1/provisioning/connections` to obtain existing managed resources.
- `DELETE /api/v1/provisioning/connections/{external_ref}` to revoke obsolete resources before exposing changes.
- `PUT /api/v1/provisioning/connections/{external_ref}` with `{ "name": "...", "params": { "driver": "postgres", "host": "...", "port": 5432, "database": "...", "username": "...", "password": "...", "read_only": false } }`.
- `Authorization: Bearer <per-runtime-token>` for each provisioning request. Responses must contain the stable connection `id` and redact secrets.

External references are `plesk-db-<Plesk database ID>`. The gateway receives only connection IDs and its runtime proxy secret; it never receives database passwords or the provisioning token. Any partial provisioning failure denies the workspace and triggers cleanup. The broker does not write Tabularis connection persistence files.

The child uses `--auth proxy --connection-mode managed-only --base-path /tabularis/w/<opaque-id>`. The gateway removes that external prefix before forwarding; the runtime applies it to asset URLs, frontend navigation and cookie paths. The current connection deep link is `/connections/<id>/editor` under that prefix.

PostgreSQL workspaces can read/write tables, use sequences and create objects inside existing permitted schemas. They cannot create new schemas or ALTER/DROP existing application-owned objects. After an administrator adds new schemas or external creator roles, sign out of Plesk and sign in again to create a fresh workspace and recompute grants. A new browser tab in the same panel session reuses the current workspace.

## Diagnosis and removal

Use `systemctl status tabularis-broker tabularis-gateway` for service status. Access logs are disabled on the workspace and private callback routes. Service errors intentionally omit credential-helper exception details. Do not publish environment values, panel cookies or private JSON files in bug reports.

`/etc/tabularis-plesk/config.json`, signing keys and `/var/lib/tabularis-plesk/journals` require protected backups if recovery is needed. Workspaces themselves are ephemeral. On a failed cleanup, inspect the generated username in the root-only journal and use the installed credential helper's `revoke` operation to retry; do not delete application users or database objects.

Uninstalling the Plesk extension stops extension-owned processes and removes only its own service units and panel route files. Configuration and failed-cleanup journals remain for explicit operator review. Never remove the shared Plesk panel configuration or the PostgreSQL HBA file as a cleanup shortcut.
