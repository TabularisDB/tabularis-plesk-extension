# Validation record

Observed on the official `plesk/plesk` Linux container, Plesk 18.0.82.3 / Ubuntu 24.04, with local MariaDB and PostgreSQL 16. Docker is only the evaluation environment. Nothing inside the extension requires Docker or its socket.

| Check | Observed result |
|---|---|
| ZIP installation through `plesk bin extension --install` | Successful |
| Native extension page for admin, customer, DB-only subuser, denied subuser | Renders through actual Plesk session |
| Effective database catalogue | Admin/customer/allowed subuser see both sample databases; denied subuser sees none |
| Role revocation using the same browser cookie | Catalogue immediately becomes empty; restoring role restores permitted databases |
| Private Unix callback | Allowed sessions receive valid signed catalogues; denied role gets 403; wrong original client IP yields no grant |
| Distinct effective identities | Admin, customer and both subusers have distinct identities |
| PostgreSQL existing tables, write, sequence | Dedicated account succeeds; real public editor SELECT returned 120 customers, 360 orders and 1,080 items and UPDATE affected 1 row |
| PostgreSQL CREATE SCHEMA | Denied as intended: no database-level CREATE grant |
| PostgreSQL future owner-created table/sequence | Default privileges work |
| PostgreSQL unrelated database via TCP and Unix socket | Denied by generated-role HBA rules |
| PostgreSQL cleanup | Login disabled, sessions terminated, role removed; its created objects retained by transfer to an unprivileged NOLOGIN owner; SECURITY DEFINER escalation test denied |
| MariaDB dedicated account reads/writes | Successful; real public editor SELECT returned 120 customers, 360 orders and 1,080 items and UPDATE affected 1 row |
| MariaDB `psa` and `mysql` databases | Denied |
| MariaDB cleanup | Generated account removed; an existing SLEEP(15) query terminated within 0.3 seconds |
| Application passwords | Unchanged in the tested provisioning paths |
| Python/PHP security/protocol suite | 23 tests: 22 pass locally; the root-only cross-UID test passes against the installed extension in Plesk. Includes blocked-cleanup stream cancellation, revoked slow uploads never reaching the runtime, unchanged authorized POST bodies, replaced ports receiving zero secret bytes, callback cookie isolation and authorized native card links |
| PHP syntax and deterministic packaging | Pass |

The real public Plesk gateway starts the pinned core runtime and loads both editors. PostgreSQL browses 5 tables and 2 views; MariaDB browses 4 tables and 1 view. Both execute SELECT/UPDATE, create a table inside an existing schema/database, insert generated identity/auto-increment values, drop their own test table and survive a direct editor URL refresh. Local MariaDB requires an explicit disabled-TLS setting because the bundled server has no TLS; this is allowed only for a literal loopback address, while remote MySQL requires verified TLS identity. No fake runtime is substituted for these checks.

Both native card actions were clicked in the actual panel and opened the matching `provisioned-plesk-db-1` PostgreSQL or `provisioned-plesk-db-2` MariaDB editor.

The extension page was checked at 390 × 844 pixels: a single panel heading, no horizontal overflow and both launch buttons visible. Native database cards receive an authorized per-database action through `pm_Hook_SimpleList`. Plesk 18.0.82 renders extension actions in the expanded card; its compact ellipsis only exposes hard-coded built-in actions and has no supported extension insertion point. The launch URL is not an access grant: the gateway independently checks the live Plesk session and selected database.

The image's bundled evaluation license permits one customer and one domain and expires on 2026-12-18 in this lab. A second independent customer/subscription, ownership transfer to a second customer, reseller impersonation, aliases/additional domains and remote database servers require further licensed integration coverage. Automated workspace tests verify that different principals, sessions and catalogue ownership produce different runtime IDs, but are not a substitute for those Plesk end-to-end checks.

Remote PostgreSQL is rejected until a supported remote-host isolation adapter exists. Existing PostgreSQL objects retain their application owner; owner-only ALTER/DROP operations remain restricted. The login cannot create new schemas; schemas created separately by an administrator or new external creator roles need a fresh workspace. These are explicit first-version limits.
