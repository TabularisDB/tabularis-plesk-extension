# Scoped AI lab validation

This follow-up used the real Plesk customer session, existing PostgreSQL and
MariaDB fixture databases, and OpenRouter with `openai/gpt-5.4-mini` on
2026-11-17. No database permissions or global application authority were expanded.
It supplements the [November 16 validation](VALIDATION.md).

## Build pins

| Artifact | Revision or SHA-256 |
| --- | --- |
| Final core UI follow-up | `04a24593348246794ae002b0a69ad24e0d3f1f3b` |
| Core bundle | `3b8778dff66614ea73103b9c6cd0826576918cd7f8b21bca541ab19e49378343` |
| Core Linux binary | `e691dc69a596c7798833d014d76636f0c1f092b0c73dd67759836f5c25e06542` |
| Extension functional revision | `d0913f3ea6590e9dd27649fea9456a8d2fc2c1b8` |
| Extension ZIP | `414dfb62f5d33f361c23fbf09db96e3e5a98b52405227e2ebbb89c9f80566c62` |

The intermediate core `9b6e755d8ef0e9f9c00afea98309515e687dabbf` passed the
provider, request-validation and lifecycle checks below. Its successful Explain
dialog also displayed a misleading legacy provider-configuration warning. The
final revision changes only that UI warning condition and its regression test;
the backend contract is unchanged.

## Observed request and lifecycle checks

| Check | Observed result |
| --- | --- |
| Disabled AI | AI controls hidden, no session AI metadata, generate returned 403 |
| Enabled session | Only fixed provider/model exposed; authorization remained database-level with high-risk capabilities false |
| PostgreSQL and MariaDB generation | Real provider responses inserted a five-product SELECT; execution required a separate Run action |
| Manual SQL execution | Five rows and two columns returned for both engines |
| PostgreSQL and MariaDB explanation | Real provider returned an explanation of the selected SQL |
| Strict request validation | 15 wrong-scope, unknown-field, empty-input and oversized-input cases returned the expected 400 or 403 |
| Existing privileged APIs | Seven legacy AI/configuration/plugin-management requests remained 403 |
| Anonymous request | Returned 403 |
| Revoked Plesk role | Existing workspace request returned 403 |
| PostgreSQL-only operator policy | PostgreSQL retained AI; MySQL generation returned 403 |
| Empty policy/catalogue intersection | Session AI metadata absent; zero provider manifests, keys or scoped configuration files in the runtime |
| Supported disable | Runtime copies removed; old AI requests returned 403 |
| Protected copies | Files owned by the non-root runtime UID with private modes; only authorized fixture connections were listed |
| Process boundary | Provider key absent from process arguments and environment |
| Restored policy | Both-database operator policy restored; services active |

Provider secrets, panel cookies, raw request recordings and private inspector
output remain outside Git. Only the explicit operator policy intersects the
signed Plesk catalogue; an AI opt-in cannot grant another database connection.
The core's built-in OpenRouter recipe takes precedence over the installed
same-ID manifest, so its executed request recipe is pinned by the core binary.

## Final browser acceptance

On final core `04a24593348246794ae002b0a69ad24e0d3f1f3b`, MariaDB generation
returned HTTP 200 in 1.82 seconds and inserted SQL without execution. A separate
manual Run returned five rows and two columns in 110 ms. Explanation returned
HTTP 200 in 1.64 seconds, displayed the expected product-price explanation and
showed no provider-configuration warning.

PostgreSQL generation returned HTTP 200 in 2.28 seconds and also inserted SQL
without execution. A separate manual Run returned the same five products and two
columns in 86 ms. Explanation returned HTTP 200 in 2.32 seconds, displayed the
expected explanation and showed no configuration warning. The real capture
preserves the distinct Generate, manual Run and Explain actions.

The final installed binary hash, private file ownership/modes, two-database
allowlist and absence of provider keys from process arguments/environment were
rechecked on this revision. The new AI core [PR #1595](https://github.com/TabularisDB/tabularis/pull/1595)
remains unmerged. The earlier core prerequisites were merged separately by a
maintainer on November 17.

## Extension verification

The full extension suite contains 38 tests, including 15 focused AI tests. The
ordinary-user run passed 37 with one root-only cross-UID proof skipped. All 38
were exercised successfully inside the actual Plesk container; the native hook
check required Plesk's PHP binary directory on PATH. PHP syntax checks covered
all ten files, and packaging passed.

## Limits

The external provider checks cover OpenRouter with the named model and these two
fixture databases. They do not establish compatibility with every provider,
model or remote database server. The evaluation license still permits one
customer/domain only. Notebook AI, unrestricted agent tools, provider selection
and global application configuration remain outside this opt-in. SQL generation
does not execute its output automatically. Source key or policy changes require
broker restart; live key rotation was not performed on the shared account.
In-flight AI cancellation, schema-only provider payloads and core secret-redaction
internals are covered by core automated tests, not by interception at the live
external provider. The live checks above do not claim that additional coverage.
