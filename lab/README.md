# Local Plesk integration lab

This lab runs the official Plesk development image on Linux and provisions a
customer, a domain, MariaDB and PostgreSQL databases, and two additional Plesk
users. It never installs Plesk on the Docker host or changes existing containers.

The pinned image was tested on November 16, 2026:

| Component | Tested version |
| --- | --- |
| Image | `plesk/plesk@sha256:1d0911e7fcb3a2d1d33d06aa30e3da6334daed720ea8106e113a05c0ac2e8924` |
| Plesk | Obsidian 18.0.82.3 |
| Container OS | Ubuntu 24.04 |
| MariaDB | 10.11.14 |
| PostgreSQL | 16.15 |
| Host Docker | 29.1.3, Linux amd64, cgroup v2 |

The image's bundled license passed `plesk bin license --check-installed-license`.
It permits one customer and one domain and reports an expiry of December 18, 2026.
Future runs must check their own license validity. These scripts neither acquire
nor purchase a license. A fresh trial or development license with additional
capacity is required to test multiple customers, subscriptions, and resellers.

## Start and provision

Requirements: Linux, Docker access, Bash, Python 3, approximately 4 GB available
memory, and sufficient disk space for the Plesk image. The container's systemd
options follow [Plesk's official Docker repository](https://github.com/plesk/docker).
They include `SYS_ADMIN`, a cgroup mount, and an AppArmor exception; this is a
development container, not a production deployment recipe.

```sh
bash lab/start.sh
python3 lab/provision.py
```

The startup script waits for Plesk initialization, replaces the image's default
administrator password, removes the image's `default-login` convenience
extension, and removes its password-reset drop-in. Generated credentials live in
`~/.local/state/tabularis-plesk-lab/credentials.json` with mode `0600`, inside a
`0700` directory. No password is placed in shell history, process arguments, or
tool output. Plesk commands receive passwords through `PSA_PASSWORD` inside the
container after a private stdin transfer.

The scripts can be rerun: existing fixtures are retained, and hardening markers
are tied to the container ID so recreating the container does not skip password
rotation. The default `tabularis-plesk-lab` container must carry the label
`com.tabularis.purpose=plesk-extension-lab`; the scripts refuse other containers.

| URL or account | Purpose |
| --- | --- |
| `https://127.0.0.1:18443/` | Plesk panel; development certificate is self-signed |
| `http://127.0.0.1:18880/` | Plesk HTTP listener |
| `http://127.0.0.1:18086/` | Test website HTTP listener |
| `https://127.0.0.1:18444/` | Test website HTTPS listener |
| `admin` | Plesk administrator; credential key `admin` |
| `tabularis-lab` | Customer; credential key `customer` |
| `dbuser@example.test` | Additional user with database management; key `subuser` |
| `nodbuser@example.test` | Additional user without database management; key `subuser` |
| `shop.example.test` | Customer domain; no DNS record is required for panel tests |

All published ports bind to `127.0.0.1`. No database ports or Docker socket are
published. Access from another computer can use an SSH tunnel:

```sh
ssh -N -L 18443:127.0.0.1:18443 user@docker-host
```

Then open the same local panel URL. Read the protected credential file locally;
do not paste its contents into an issue or commit. When configuring the extension,
use the exact browser origin `https://127.0.0.1:18443`.

Optional environment variables:

| Variable | Default |
| --- | --- |
| `PLESK_LAB_CONTAINER` | `tabularis-plesk-lab` |
| `PLESK_LAB_STATE_DIR` | `~/.local/state/tabularis-plesk-lab` |
| `PLESK_LAB_IMAGE` | Pinned digest above |
| `PLESK_LAB_DOMAIN` | `shop.example.test` |
| `PLESK_LAB_HOSTNAME` | `plesk-lab.test` on container creation; optionally updates the Plesk hostname |
| `PLESK_LAB_PUBLIC_IP` | Unset; optionally records the container's public NAT address in Plesk |
| `PLESK_LAB_PANEL_PORT` | `18443` |
| `PLESK_LAB_PANEL_HTTP_PORT` | `18880` |
| `PLESK_LAB_HTTP_PORT` | `18086` |
| `PLESK_LAB_HTTPS_PORT` | `18444` |

Choose unused ports before the first start. Port changes require recreating this
lab container. State can alternatively be stored under the Git-ignored
`lab/.state/`; do not select a tracked directory.

When using a real DNS name behind a reverse proxy, pass its public address through
`PLESK_LAB_PUBLIC_IP`. This lets Plesk recognize the address when validating domain
names without disabling its domain protection policy. These settings update only
the lab container; they do not publish DNS, configure the host proxy, or obtain
public TLS certificates.

The optional [Apache template](apache.example.conf) preserves the requested host,
supports WebSockets, and replaces incoming forwarding headers before proxying to
the loopback panel and website HTTPS ports. Use dedicated virtual hosts and run
the host's configuration check before reloading. Obtain valid public certificates
separately; the template contains placeholders and no private key material.

Plesk's panel web server does not include nginx's real-IP module. Plesk instead
supports specific trusted proxy IPs through its
[panel configuration](https://support.plesk.com/hc/en-us/articles/12378054592023-IP-Access-Restriction-Management-doesn-t-work-as-expected-when-the-hostname-is-behind-Cloudflare).
For a host proxy reaching this lab through the default Docker bridge, configure
`[panel] realIpFrom = 172.17.0.1` in the container's `panel.ini` and pass the same
address to the extension installer as `--trusted-panel-proxy 172.17.0.1`.
Substitute the actual gateway address if different. Both sides must agree so that
the private callback preserves Plesk's session IP checks. Do not disable those
checks to make a reverse proxy work.

## Fixtures and extension installation

Both `tabularis_shop_pg` and `tabularis_shop_mysql` contain 120 customers,
30 products, 360 orders, and 1,080 order items, with foreign keys, Unicode text,
nullable fields, JSON, and an aggregate view. PostgreSQL also includes 360 audit
events, arrays, JSONB, identity sequences, and a second aggregate view. All records
are synthetic. Application users are `shop_pg_owner` and `shop_mysql_owner`.

PostgreSQL is installed through the Plesk installer and registered as the local
server, rather than managed independently of Plesk. See the official
[database server documentation](https://docs.plesk.com/en-US/obsidian/administrator-guide/database-servers.59427)
and [database CLI reference](https://docs.plesk.com/en-US/obsidian/cli-linux/using-command-line-utilities/database-databases.75671/).

Build and install the extension ZIP from the extension implementation branch:

```sh
python3 scripts/package.py
docker exec -i tabularis-plesk-lab sh -c 'cat > /root/tabularis.zip' < dist/tabularis-0.1.0.zip
docker exec tabularis-plesk-lab plesk bin extension --install /root/tabularis.zip
```

The stdin copy works even when a temporary directory is not visible to the Docker
daemon. Configure the verified Tabularis binary and Web UI with the extension's
runtime installer before opening workspaces. Plesk's Docker extension is not used:
Tabularis runs as isolated native processes inside the Plesk lab container.

## Verify real privileges and sessions

After installing a ZIP containing `credentials.php`:

```sh
python3 lab/verify.py
```

This creates disposable `tab_` accounts and uniquely named test tables in each
fixture database. It checks existing-table reads and writes, generated identity
values, future application-owned tables and sequences, unchanged application
credentials, repeated provisioning without password replacement, denial of an
unrelated database, and account revocation. Revocation must preserve a table
created during the extension session. The verifier drops only its own test
tables and removes its generated accounts afterward.

A security regression also creates a `SECURITY DEFINER` function whose body
attempts to read a protected administrator-owned table. The function must fail
both before and after account revocation. Preserved PostgreSQL objects belong
to a separate `tab_ret_` role that cannot log in, inherit roles, create databases
or roles, bypass row security, or act as superuser. Cleanup must never transfer
user-authored executable objects to `postgres` or an application owner. Retained
roles are intentional while their objects exist; the verifier removes only the
empty retained roles associated with its own disposable fixtures.

Active-query checks start a long query as the generated account and a short query
as the application account. Revocation must stop the generated account's query
within three seconds while the application query finishes normally. MySQL
`DROP USER` alone does not stop existing sessions, so this is checked separately
from a new-login denial.

After configuring the extension's callback and runtime:

```sh
python3 lab/verify.py --with-panel
```

This additionally performs actual Plesk logins, verifies the signed database
catalog for the administrator, customer and permitted subuser, denies the other
subuser, and checks that changing a role revokes an existing session immediately.
It also exercises the private Unix callback and verifies that an incorrect
original client IP cannot produce a signed grant.
Cookies are saved only in protected local state files. The role is restored in a
`finally` block. TLS verification is disabled only for the explicitly loopback,
self-signed lab endpoint. A public HTTPS origin can be tested with
`--origin https://panel.example.com`; its certificate is verified normally.

After those public-origin session checks, exercise the running gateway with
Python's `aiohttp` dependency installed:

```sh
python3 lab/verify_runtime.py --origin https://panel.example.com
```

This opens a permitted subuser workspace, rejects the same URL when used by the
customer, denied subuser or anonymous browser, then revokes the live role. An
already established WebSocket must close through its own periodic authorization
check without a subsequent HTTP request triggering reconciliation. HTTP access
must also be denied. The role is restored in a `finally` block; application
passwords and database contents are unchanged.

## Findings from the first real run

- The SDK autoloads `Modules_Tabularis_Catalog` from `plib/library/Catalog.php`.
- `pm_Session::getClient()` identifies a subuser's owner. The effective
  `Session::get()->auth()->getUserRow()` distinguishes owner and additional-user
  identities. The actual `databasesManagement` permission and subscription scope
  must be checked. A database-only subuser can fail generic domain-access checks
  despite having valid database access.
- Administrator, customer and the permitted subuser saw both fixture databases;
  the denied subuser saw none. Revoking the permitted role with an existing
  cookie removed access immediately. Suspending the subscription removed its
  database catalog, and restoring it restored access.
- A second Plesk PostgreSQL account initially could not read existing tables or
  advance existing sequences. Explicit table, sequence, schema and creator-role
  default grants were required. The generated account was then able to use both
  existing and future objects without changing the application password.
- PostgreSQL's default local TCP HBA rule allowed `PUBLIC CONNECT` to another
  database. A guard for each generated account was required; revoking that user's
  database privilege alone does not override a `PUBLIC` grant. Both TCP and Unix
  socket connections to the other database were rejected after adding the guard.
- PostgreSQL alteration or removal of application-owned objects remains subject
  to ownership rules. The helper does not grant application-owner membership or
  superuser rights. Remote PostgreSQL requires a separate guarded adapter and
  fails closed without one.
- New PostgreSQL objects can be created in an existing authorized schema. The
  generated login cannot create a new schema because it has no database-level
  `CREATE` privilege.
- MariaDB's scoped account read and wrote its fixture database and was denied
  access to `psa` and `mysql`.

The one-domain bundled license prevented a second tenant or subscription from
being provisioned. Cross-tenant and reseller browser tests therefore remain
unverified in this lab; they must not be reported as passed. The scoped database
denial checks above are independent of that limitation.

## Stop or remove only this lab

```sh
docker stop tabularis-plesk-lab
docker start tabularis-plesk-lab
```

The container's writable layer holds the lab databases and Plesk state. Removing
the container deletes that state:

```sh
docker rm -f tabularis-plesk-lab
```

Do not use global Docker pruning or remove unrelated containers. Retain protected
local credentials if the lab will be recreated, or delete only this lab's state
directory when its credentials and cookies are no longer needed.
