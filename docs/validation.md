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
| PostgreSQL existing tables, write, sequence | Dedicated account succeeds |
| PostgreSQL future owner-created table/sequence | Default privileges work |
| PostgreSQL unrelated database via TCP and Unix socket | Denied by generated-role HBA rules |
| PostgreSQL cleanup | Login disabled, sessions terminated, role removed; its created objects retained by transfer to an unprivileged NOLOGIN owner; SECURITY DEFINER escalation test denied |
| MariaDB dedicated account reads/writes | Successful |
| MariaDB `psa` and `mysql` databases | Denied |
| MariaDB cleanup | Generated account removed |
| Application passwords | Unchanged in the tested provisioning paths |
| Python security/protocol tests | Pass, including a live local WebSocket closed on permission revocation |
| PHP syntax and deterministic packaging | Pass |

Full gateway-to-Tabularis UI/SQL verification awaits the pinned core runtime integration and is recorded in the lab report. No fake runtime is substituted for this check.

The image's bundled evaluation license permits one customer and one domain and expires on 2026-12-18 in this lab. A second independent customer/subscription, ownership transfer to a second customer, reseller impersonation, aliases/additional domains and remote database servers require further licensed integration coverage. Automated workspace tests verify that different principals, sessions and catalogue ownership produce different runtime IDs, but are not a substitute for those Plesk end-to-end checks.

Remote PostgreSQL is rejected until a supported remote-host isolation adapter exists. Existing PostgreSQL objects retain their application owner; owner-only ALTER/DROP operations remain restricted. Future schemas or new external creator roles need a fresh workspace. These are explicit first-version limits.
