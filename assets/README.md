# Presentation media

## Continuous WooCommerce workflow

[`videos/woocommerce-workflow.mp4`](videos/woocommerce-workflow.mp4), its
[matching GIF](videos/woocommerce-workflow.gif) and
[JPEG poster](videos/woocommerce-workflow.jpg) show one continuous browser take
recorded on 2026-11-17. The source runs for 85.734067 seconds at normal speed;
the constant-frame-rate export is 85.73 seconds. No loading waits, actions or
idle intervals were removed, and no other take was inserted.

The README embeds a smaller [GIF preview](videos/woocommerce-workflow-preview.gif)
of the same complete sequence at 640×427 and 6 fps (about 9 MB). Clicking it
opens the full-quality MP4. The original 960×640 GIF remains available separately.

The real Plesk 18.0.82.3 lab on Ubuntu 24.04 runs WordPress 7.1.4,
WooCommerce 11.3.0 and Storefront 4.6.2 in English. The launch was recorded in
Plesk’s administrator view. The shop is installed under
`/coffee/`, with HPOS enabled in the MariaDB database `tabularis_woocommerce`
and the `wp_` table prefix. Its 24 products, 300 orders and nine separate refund
records are synthetic fixtures created through WooCommerce APIs. Completed and
processing orders total EUR 14,185.03; the chart reports gross order value for
those statuses, not net revenue.

The capture uses core `04a24593348246794ae002b0a69ad24e0d3f1f3b` and deployed
extension `d0913f3ea6590e9dd27649fea9456a8d2fc2c1b8`. Scoped AI requires the
unmerged [core PR #1595](https://github.com/TabularisDB/tabularis/pull/1595);
the extension-side policy is already merged. The wider authorization and
PostgreSQL/MariaDB checks are recorded in the existing
[lab validation report](../lab/VALIDATION.md) and
[AI evaluation](../lab/AI_VALIDATION.md). This media update changes no runtime
behavior and does not claim a new authorization-boundary test run.

The uninterrupted sequence shows:

- Launch the WooCommerce database from its native Plesk card. A default empty
  Console appears and is visibly closed; there is no SQL or result data at entry.
- Open `wp_wc_orders`, sort newest first, and inspect the product stock table.
- Load and run the prepared **Orders to Fulfill** and **Best-Selling Products**
  saved queries; maximize the real five-product Bar chart, inspect the first
  product’s 183 ordered units, and restore the SQL editor.
- Open a new console and ask SQL Editor AI for daily EUR order totals. The
  administrator-selected OpenRouter model `openai/gpt-5.4-mini` returns actual
  SQL, followed by a separate manual Run. Its 15 daily results are shown as a
  Line chart, then history accumulated during this same session is opened.
- Create **Weekend Campaign Review**, add and preview a Markdown note, place
  it above the SQL cell, paste the generated query, and choose Run All. The
  notebook returns the same 15 daily rows and reports one successful SQL cell.

Four saved queries were prepared ahead of time; none is open at entry.
Rehearsal tabs, history and notebooks in this workspace were cleared before
recording. Editor input uses normal typing and a standard paste into the real
editor model. The native Plesk action's link target was changed to the same tab
solely to permit one uninterrupted tab capture; its authenticated launch URL and behavior were
retained. No query results or application screens were fabricated.

The fixed Safari-style frame and background are decorative; the recording
comes from a Linux browser. Native 2880×1800 pixels are retained through domain
replacement and gentle camera moves. Plesk heading/card and Explorer domain
labels are replaced with `test.tabularis.local`; the decorative address bar uses
`plesk.tabularis.local`. The Plesk footer is below the captured viewport. A
briefly narrow Explorer label uses an ellipsis. Domain replacement happens before
zooming. No public URL, login screen, password, session cookie or provider key
appears in these three deliverables.

The MP4 is 1920×1280 at 60 fps, without audio, with fast-start metadata. Its
looping GIF mirrors the same continuous edit at 960×640 and 12 fps. The poster
shows the complete, settled best-selling-products Bar chart at 35.2 seconds
from this same capture, with no tooltip covering data. Complete chart axes and
labels remain visible, including every date on the daily Line chart.

## Earlier Plesk overview and screenshots

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
