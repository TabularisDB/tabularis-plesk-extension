# Real Plesk lab validation

The checks below used the real public HTTPS panel and synthetic application
databases on 2026-11-16. They did not use a simulated Plesk API or mocked query
results. Core and extension revisions are pinned separately below.

## Pinned builds

| Artifact | Tested revision or SHA-256 |
| --- | --- |
| Tabularis core | `0d2a6a098f8369653b918d1e78d7f4eeeac65d8a` |
| Core bundle | `a54eeee7a00638083a6b5284134883146a2eab656a645077ee83181cedd2d4a6` |
| Core Linux binary | `4f9cd68bfeeaa0dab0c293760c1e7a812528aa9c23f0c0e2c2489506b93d109a` |
| Plesk extension | `213ca5e5e29f450b04f5c5cb279033fcdb805f8a` |
| Extension ZIP | `a8c6d8d0b377463ddaff6cf74ad1d9e803e22970dacc2a432050ca9acc6179a8` |

The 21 extension tests passed across the ordinary-user run (20 passed, one root
test skipped) and the real Plesk container's root-only test (one passed). That
test keeps the legitimate child alive while a different UID replaces its TCP
listener, and confirms that no token or database password reaches the replacement.
PHP syntax checks covered all nine PHP files; Python/Bash syntax checks,
`git diff --check`, and reproducible ZIP packaging also passed.

## Environment

- Plesk Obsidian 18.0.82.3 on Ubuntu 24.04, in the pinned official Docker image
  documented in [README.md](README.md).
- PostgreSQL 16.15 and MariaDB 10.11.14, with database ports unpublished.
- Panel: `https://plesk.cloud.dueclic.com`.
- Subscription: `test.intern.cloud.dueclic.com`.
- Databases: `tabularis_shop_pg` and `tabularis_shop_mysql`, explicitly associated
  with the subscription's website through Plesk's supported CLI.
- Each engine has 120 customers, 30 products, 360 orders and 1,080 order items.
  PostgreSQL also has 360 audit events, arrays, JSONB and identity sequences.
- Host Apache terminates public TLS and forwards to loopback-only Docker ports.
  Plesk trusts only the Docker gateway for the original client IP. Existing host
  sites and other Docker workloads were left intact.

## Reproducible checks

```sh
env PLESK_LAB_DOMAIN=test.intern.cloud.dueclic.com \
  PLESK_LAB_HOSTNAME=plesk.cloud.dueclic.com \
  PLESK_LAB_PUBLIC_IP=151.84.10.117 python3 lab/provision.py
python3 lab/verify.py --with-panel --origin https://plesk.cloud.dueclic.com
python3 lab/verify_runtime.py --origin https://plesk.cloud.dueclic.com
```

The runtime verifier requires `aiohttp`. Credentials and session cookies are
read from protected local state; none are included in this repository.

| Check | Observed result |
| --- | --- |
| Existing and future application objects, both engines | SELECT and DML succeeded; identity/sequence values worked |
| Application credentials | Original application logins still succeeded after provisioning and revocation |
| Repeat provisioning | The original generated password remained valid; no silent rotation |
| Other database access | PostgreSQL and MariaDB denied the unrelated database |
| PostgreSQL object preservation | User-created data survived revocation under a restricted `NOLOGIN` owner role |
| PostgreSQL executable-object cleanup | A preserved `SECURITY DEFINER` function could not acquire administrator privileges |
| Active query revocation | Both engines cancelled the generated account's long query while an application query completed |
| Plesk effective identities | Administrator, customer and database-enabled subuser had distinct identities and the expected two databases |
| Denied role and live role change | Denied subuser could not open a workspace; an existing permitted session lost access on role removal |
| Private callback | Signatures verified; incorrect original client IP was rejected |
| Workspace URL reuse | Customer, denied subuser and anonymous requests could not use the permitted subuser's workspace URL |
| Established WebSocket | Independently closed in 2.05 seconds after role revocation, without another HTTP request triggering reconciliation |
| Restored role | Opened a newly authorized workspace successfully |

## Actual browser acceptance

The final checks used the shared preview browser over the public HTTPS origin.
Both supported native database-card actions were clicked and opened the correct
editor route. Customer and database-enabled subuser pages each contained two
actions; the denied subuser page contained none.

- PostgreSQL displayed the `public` schema, five tables and two views. A SELECT
  returned the correct database and 120 customers; an existing-row UPDATE affected
  one row. Earlier UI checks also created, inserted into, read and removed an
  identity table inside `public`, verifying generated value `1`.
- MariaDB displayed one authorized database, four tables and one view. SELECT and
  existing-row UPDATE passed. The browser also created an auto-increment table,
  inserted and read generated value `1`, and removed that test table using the
  actual confirmation dialog. The loopback-only TLS policy fixed the bundled
  MariaDB server's lack of TLS without weakening remote certificate verification.
- Both fixture databases returned 360 orders and 1,080 order items. The gallery
  and recording use formatted SELECTs from the real `order_summary` view and show
  ten result rows. Presentation queries do not modify fixture data.
- Direct editor refresh opened the same database. After clicking **Maybe later**,
  the central community dialog stayed dismissed across refresh, the editor loaded,
  and no `save_config` request was made. The separate sidebar callout also stayed
  dismissed in the same workspace.
- At 390 by 844 CSS pixels, the extension page had one H1, document width 390,
  and both launch buttons fully inside the viewport. The native PostgreSQL card's
  launch action was also visible and clickable at that width.

Temporary SQL objects were removed. Stable panel, application and system
credentials were not rotated by the tests.

## Scope limits

The bundled evaluation license permits only one customer and one domain. A
second tenant, cross-tenant browser isolation, reseller sessions and reseller
impersonation could not be exercised. Remote PostgreSQL remains rejected without
a separate guarded adapter; remote MySQL was not available for a live test.

PostgreSQL grants cover existing schemas and known application creators. New
objects can be created inside an authorized existing schema, but database-level
`CREATE SCHEMA` and owner-only ALTER/DROP of application objects remain denied.
New external creator roles or schemas require fresh grant reconciliation. The
lab checked those restrictions instead of granting broad owner membership.

The supported Plesk hook adds the launch action to the expanded database card;
the native ellipsis menu remains Plesk's own Web Admin/Remove menu. Plesk's long
native domain heading can overflow on a narrow phone display; the extension's
own page does not. Global application configuration, plugin management and
AI/SSH services remain outside the restricted database session's authority.

Original screenshots and the raw recording are kept outside Git. The published
video must remove public URLs and domain labels before decorative framing. No
login, password, cookie, grant or API token is included in the captured scenes.
