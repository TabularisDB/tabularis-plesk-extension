# Presentation media

These assets show real browser sessions in Plesk 18.0.82.3 on Ubuntu 24.04,
against the synthetic PostgreSQL and MariaDB fixtures documented in
[the lab validation report](../lab/VALIDATION.md). All captures use Tabularis
core `0d2a6a098f8369653b918d1e78d7f4eeeac65d8a`.

The four screenshots and the recording's brief native Plesk card introduction
were captured on 2026-11-16 with extension
`213ca5e5e29f450b04f5c5cb279033fcdb805f8a`. The query-to-chart footage was
captured on 2026-11-17 with deployed extension
`ee39af503a15391cc299933f428ad8540a8cb0db`. The subsequent repository changes
were documentation and presentation assets, not changes to the captured UI.

The recording demonstrates actual SQL execution and chart generation:

- PostgreSQL: format and execute a country-revenue query, open its Bar chart,
  maximize the chart and inspect country values.
- MariaDB: aggregate order revenue by month, open the automatically selected
  Line chart, then explicitly switch to Bar and back to Line. The six points
  represent January through June 2026.

The decorative window frame and background follow the Tabularis governance
release-media tools. The video uses a fixed decorative Safari-style frame with a
local address bar; the browser capture itself is neither Safari nor macOS. Eased
camera moves crop into the real application content to follow SQL entry, Run and
chart controls. Full application views establish orientation before and after
close-ups; complete charts retain their axes, labels and values during inspection.
The new source footage retains its original 2880×1800 resolution through the
content zooms. Rehearsal, page-loading and idle waits are removed in the montage;
the sequence of demonstrated interactions and the query results are unchanged.

Screenshots retain the real panel content. The MP4, GIF and poster replace public
addresses and domain identifiers with `plesk.tabularis.local` and
`test.tabularis.local` before framing or zooming. The narrow PostgreSQL Explorer
label uses a natural ellipsis; the full local site name remains in the decorative
tab title. No login, password, session cookie or API token is shown.

The MP4 is 40.8 seconds at 1920×1280 and 60 fps, with no audio. The looping GIF
contains the same edit at 960×640 and 12 fps. The JPEG poster shows the complete
PostgreSQL Bar chart without a tooltip covering the data.

Only final PNG screenshots, the sanitized MP4/GIF and their JPEG poster belong here.
Private source footage and the separate English/Italian PDF reports stay outside
Git. The source footage must not be copied into a public branch or release.
