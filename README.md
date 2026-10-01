# Tempo — local productivity dashboard

## Start

Double-click **Start Tempo.cmd** (Python 3.10+ required), or run `python server.py` in this folder. Open http://127.0.0.1:8765. Keep the server running while using the app.

The app supports manual activity logging immediately. Start/stop timers survive page reloads and server restarts. Completed entries, notes and chosen focus activities are stored in `data.sqlite3` beside the app. Back up this file to keep your history.

## Automatic tracking

Download and run [ActivityWatch for Windows](https://activitywatch.net/downloads/). Its default local server must be running at http://127.0.0.1:5600, with both the window and AFK watchers enabled. Click **Refresh** in Tempo. If you have multiple computers in ActivityWatch, select one from the computer selector.

Tempo reads active application events through ActivityWatch’s REST query API. Idle periods are excluded by intersecting window events with `not-afk` periods. It does not install or secretly start a background recorder. Website-level tracking requires ActivityWatch’s browser extension; this version of Tempo groups automatic time by application, not individual website. ActivityWatch’s own dashboard can show website detail.

## Features

- Daily and hourly activity breakdowns, with clickable hours.
- Monday–Sunday weekly totals per activity and export to CSV.
- Manual entries for offline work, with accomplishment notes in the weekly report.
- Persistent start/stop timer and activity deletion.
- Focus activities chosen by you, with transparent, rules-based improvement suggestions.
- Sample week for exploring the dashboard, kept separate from real data.

## How time is counted

Reports use your browser/computer timezone. Intervals are clipped at report and hour boundaries. Overlapping time is counted once; manual entries override automatic events. Manual entries may not overlap each other, end in the future or exceed 24 hours. Discard timers longer than 24 hours and enter separate manual entries. The hourly chart displays local clock hours; on a daylight-saving fallback day a repeated hour is combined. Minutes displayed are rounded; CSV hours have two decimals.

The previous-week caption is a total, not a like-for-like comparison with an incomplete current week. Insights describe observed time, not cognitive focus or quality. ActivityWatch does not infer what you accomplished; use manual notes for that context. Summaries are calculated when the dashboard opens or refreshes. No email delivery or scheduled reports are configured.

## GitHub research and implementation

Selected foundation: [ActivityWatch/activitywatch](https://github.com/ActivityWatch/activitywatch), MPL-2.0. Inspected its [Vue dashboard repository](https://github.com/ActivityWatch/aw-webui) locally and its [REST API documentation](https://docs.activitywatch.net/en/latest/api/rest.html). [Kimai](https://github.com/kimai/kimai) was also reviewed but is geared toward timesheets and project reporting rather than automatic desktop activity capture.

Tempo is a new companion dashboard integrated with ActivityWatch through its local API; it is not an upstream ActivityWatch release or a modified copy of its dashboard. No upstream source was copied into this deliverable. Python's standard library serves the app and SQLite stores manual data; no npm install is required.

## Development and checks

`python server.py --no-browser` starts the local server. `node tests/analytics.test.mjs` verifies aggregation, overlap and boundary behavior. `python -m unittest discover -s tests` verifies entry validation.

Only the loopback interface is bound. Writes require same-origin JSON requests. The app never sends activity to a cloud service. Keep it local; it is not designed as a public multi-user server.
