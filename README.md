# Tabularis for Plesk

Native Plesk Linux extension for MySQL, MariaDB and PostgreSQL. Work is proposed through unmerged pull requests; this is an evaluation implementation, not a released extension.

The panel handles login and database permissions. A local broker starts independent, unprivileged Tabularis Web processes and provisions scoped database connections. An unprivileged gateway checks the current Plesk session on every HTTP request and periodically on established WebSockets.

Requirements: Plesk Obsidian 18.0.59+, Linux, panel PHP 8.1+, Python 3.10+, `python3-aiohttp`, systemd, and a pinned Tabularis Web build with the provisioning, managed-only and runtime-base-path changes. Initial integration is validated on Ubuntu 24.04 / Plesk 18.0.82. Other distributions require validation.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/package.py
# On the evaluation Plesk server, as root:
plesk bin extension --install /path/to/tabularis-0.1.0.zip
```

Installation does not fetch an arbitrary latest binary or overwrite operator configuration. The runtime and its SHA-256 must be supplied explicitly. Uninstalling the extension stops its own services and retains state and extension-created database users for deliberate cleanup; application databases and users are never deleted.

See [runtime installation](docs/runtime.md), [architecture and security](docs/architecture.md), and [observed validation and limitations](docs/validation.md).

See [the open implementation issues](https://github.com/TabularisDB/tabularis-plesk-extension/issues) and the [Apache 2.0 license](LICENSE).
