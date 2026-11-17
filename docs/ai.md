# Operator-managed SQL assistance

AI is disabled on new installations. An administrator can opt in to the core's
scoped SQL generation and explanation API using one fixed provider and model.
The existing Plesk session, managed connection catalogue and database credentials
continue to control access. This integration grants no global configuration,
provider-selection, agent-tool or unrestricted administrator access.

Use a reviewed Tabularis Web build whose `web --help` advertises
`TABULARIS_WEB_AI_CONFIG_FILE`. The installer refuses an AI opt-in against an older
binary. The core must validate the current saved connection, database and schema
on every AI request and build generation context on the server. The extension
does not supply a substitute AI endpoint or execute generated SQL.

## Configure the operator policy

Place a reviewed declarative AI provider ZIP, optional provider key and operator
JSON in a protected directory on the Plesk host. Files and every ancestor must be
root-owned without group or other write access. The operator JSON and key must
also have no group or other read access; use directory mode `0700` and file mode
`0600`. Symlinks, unsafe ZIP paths, mismatched provider IDs and non-AI packages are
rejected. The package must contain a root `.tabularium` manifest file; only that
manifest and an optional `LICENSE` are installed in runtime homes.

The pinned core's built-in provider recipes can take precedence over installed
manifests, including for `openrouter`. Copying a provider ZIP provides a uniform
deployment layout; it does not override a built-in request recipe. Review the
pinned core as well as the package. Endpoint settings apply only when supported
by the selected provider's effective recipe.

Example `/etc/tabularis-plesk/ai/operator.json`:

```json
{
  "provider": "openrouter",
  "model": "your-reviewed-model",
  "provider_package": "/etc/tabularis-plesk/ai/openrouter.zip",
  "api_key_file": "/etc/tabularis-plesk/ai/openrouter.key",
  "settings": {},
  "databases": [
    {"id": 1, "schemas": ["public"]},
    {"id": 2, "schemas": ["shop_mysql"]}
  ]
}
```

Database IDs are Plesk database IDs, not client-supplied connection IDs. Replace
the example IDs, schema names, package and model with the reviewed deployment
values. PostgreSQL schema names are explicit; wildcards are not supported. For
MySQL/MariaDB, the schema must equal the selected database name. The operator
allowlist only narrows the current Plesk catalogue: it cannot add another tenant's
connection. A workspace with no matching entry receives no AI configuration,
provider package or key.

`settings` contains only the selected provider's settings, such as its documented
`base_url` for a compatible endpoint. The endpoint and model are administrator
choices. Omit `api_key_file` only for a provider that supports keyless operation
or declares `optional_api_key: true` in its manifest. Do not put keys in
command-line arguments, endpoint URLs, browser settings or Git. SQL assistance
sends the submitted prompt/query and, for generation, bounded schema metadata to
the selected provider. Choose the provider and allowed schemas according to the
deployment's data-handling requirements.

Install the extension ZIP first, then add this option to the regular verified
runtime installation command:

```sh
python3 scripts/install.py \
  --binary /opt/tabularis/<reviewed-commit>/tabularis \
  --sha256 <verified-binary-sha256> \
  --web-root /opt/tabularis/<reviewed-commit>/web-ui \
  --public-origin https://panel.example.test:8443 \
  --ai-config-file /etc/tabularis-plesk/ai/operator.json
```

Retain any `--trusted-panel-proxy` arguments required by the deployment. The
installer validates the protected policy and provider before changing services.
An upgrade with neither AI option preserves the existing opt-in. A new install
without `--ai-config-file` leaves AI disabled.

## Private runtime state

The broker reads the policy, provider manifest/settings and optional key once at
startup. For each workspace it intersects the operator grants with the signed,
currently authorized Plesk catalogue and derives managed IDs such as
`provisioned-plesk-db-1`. Database names come from that catalogue.

Before starting the unprivileged process, the broker writes private copies under
the workspace home, using its Unix UID, directory mode `0700` and file mode `0600`:

- `.config/tabularis/config.json`: settings for the selected provider only.
- `.local/share/tabularis/plugins/ai-assistant/<provider>/.tabularium`: its manifest.
- `ai/provider.key`: optional provider key.
- `ai/scoped.json`: fixed provider/model and the workspace's connection/schema list.

Only the path to `ai/scoped.json` is added to the constructed runtime environment
as `TABULARIS_WEB_AI_CONFIG_FILE`. No provider environment is inherited. The source
key path and its value are not included in panel grants, PHP configuration,
gateway responses, launch URLs or broker journals. Runtime homes and their provider
copies are removed by the existing revocation, idle expiration and recovery paths.
Preparation failures are journaled and cleaned before a process can launch.

## Rotate or disable

Changing a key, model, endpoint, package or allowlist requires restarting the broker:

```sh
systemctl restart tabularis-broker.service
```

This ends existing workspaces, revokes their generated database accounts and loads
a fresh policy snapshot. Users reopen their database from Plesk. Editing a source
file alone does not mutate a running process's AI policy or key.

To disable AI, rerun the verified installer command with `--disable-ai` instead of
`--ai-config-file`. It removes the opt-in and restarts services. Existing source
files are preserved for administrator-controlled retention or removal. Rolling
back to a core build without scoped AI support requires disabling AI first.

## Validation

Focused tests exercise disabled mode, malformed/missing configuration, source
ownership and permissions, ZIP/provider validation, explicit schema grants,
catalogue intersections, exact private runtime paths, keyless providers, rotation,
cleanup and partial preparation failure. Real provider compatibility, per-request
core denials and browser behavior must also be checked with the pinned core build
in the Plesk lab; local filesystem tests do not establish those results.
