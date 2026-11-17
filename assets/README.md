# Presentation media

These assets show real browser sessions in Plesk 18.0.82.3 on Ubuntu 24.04,
against the synthetic PostgreSQL and MariaDB fixtures documented in the
[lab validation report](../lab/VALIDATION.md). The optional AI scenes use the
separately pinned [scoped AI evaluation](../lab/AI_VALIDATION.md).

The four screenshots and the brief native Plesk card introduction were captured
on 2026-11-16 with core `0d2a6a098f8369653b918d1e78d7f4eeeac65d8a` and
extension `213ca5e5e29f450b04f5c5cb279033fcdb805f8a`. The other non-AI scenes
were captured on 2026-11-17 using the same core and deployed extension
`ee39af503a15391cc299933f428ad8540a8cb0db`. The real SQL Editor AI sequence
uses core `04a24593348246794ae002b0a69ad24e0d3f1f3b` and extension
`d0913f3ea6590e9dd27649fea9456a8d2fc2c1b8`. Documentation and presentation
changes do not alter the UI represented by those capture pins.

The overview demonstrates these actual interactions:

- Open PostgreSQL from its native Plesk database card; browse the products grid
  and sort prices in descending order.
- Open query history, select a previous statement and execute it in a new console.
- Name and execute a notebook SQL cell, add and preview Markdown notes, reorder
  cells, Run All and open the Notebooks sidebar.
- Run a customer/order join in the visual query builder, inspect and run
  its generated SQL, then view five tables and four foreign-key relationships
  in the schema diagram.
- With administrator opt-in, generate SQL through the fixed OpenRouter model,
  run it using a separate manual action and request an explanation in the SQL
  Editor. Notebook AI and unrestricted agent tools are not enabled by this policy.
- Format a PostgreSQL country-revenue query, open its Bar chart and inspect real
  country values. In MariaDB, switch a monthly-revenue chart explicitly from Bar
  to Line and inspect the six points for January through June 2026.

The decorative window frame and background follow the Tabularis governance
release-media tools. The video uses a fixed Safari-style frame with a local
address bar; the capture itself is a Linux browser, neither Safari nor macOS.
Eased camera moves follow the real application controls, preserving full views
before and after close-ups. Complete charts retain their axes, labels and values.
The original 2880×1800 capture detail is retained through content zooms.
Rehearsal, loading and idle waits are removed; actions and query results are real.
The grid sequence demonstrates descending price sorting.

Screenshots retain the real panel content. The MP4, GIF and poster replace public
addresses and domain labels with `plesk.tabularis.local` and
`test.tabularis.local` before framing or zooming. A narrow Explorer label may use
a natural ellipsis; the full local site name remains in the decorative tab title.
No login, password, session cookie or provider key is shown.

The MP4 is 86.27 seconds at 1920×1280 and 60 fps, without audio; the
looping GIF mirrors the same edit at 960×640 and 12 fps. The retained JPEG poster
shows a complete PostgreSQL Bar chart from the same November 17 chart capture,
without a tooltip covering the data.

Only final PNG screenshots, the sanitized MP4/GIF and their JPEG poster belong
here. Private source footage, rendering scripts and separate English/Italian PDF
reports stay outside Git. Source recordings must not be copied to a public branch
or release.
