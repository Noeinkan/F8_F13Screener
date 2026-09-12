# The public demo

`https://13f.demos.noeinsolutions.com/` is a read-only copy of this dashboard
that a stranger can be handed a link to. It is the same React and FastAPI code
the real screener runs; what differs is that it reads a frozen snapshot instead
of the live database, and that entry goes through an email gate.

The durable record of what is published and where lives in
[`demo/demo.json`](../demo/demo.json). The landing page's build card is
generated from it — see `W8_NoeinSolLandingPage/docs/BUILDS_DEMOS.md` for that
side of the arrangement.

## What a visitor meets

1. They land on the gate and leave an email address.
2. A link arrives in that inbox, good for 30 minutes.
3. Following it sets a session cookie that lasts 4 hours.
4. From there, the dashboard: overview, fund analysis, consensus trends and
   holdings search, all over the snapshot.

Nothing is stored about them. Both the link and the session are stateless
HMAC-signed strings — there is no table of addresses, so there is nothing to
purge, leak or keep in step with a retention promise. If `DEMO_NOTIFY_EMAIL` is
set, one line goes to that address saying who asked; that inbox is the only
record.

**The gate is not protecting secrets.** Every figure on the demo comes from
filings the SEC publishes. It is there so entry is deliberate and attributable
to an address. What makes the demo safe to expose is underneath it: the API
opens a read-only copy of a frozen file, and there is no route that writes.

## What is switched off

| | Why |
| --- | --- |
| `POST /api/cache/refresh` | Spawns a real SEC download on the server. |
| `GET /api/cache/refresh/status` | Nothing to report; no refresh can run. |
| `GET /api/overview/exports/full` | Streams every row of the snapshot. The per-view CSV downloads all work. |
| The sidebar's Refresh button and the database paths | The paths are the server's, not the visitor's business; the banner says which snapshot is on screen instead. |

Each is refused twice: the demo gate middleware stops the request before it
reaches a router, and the router refuses again for any caller that arrives
another way.

## The data

`demo/fixtures/13f_demo.duckdb` — 9.5 MB, 223,501 positions from 239 filings by
52 funds, covering the four filing quarters 2025-Q3 through 2026-Q2, with the
most recent filing dated **1 June 2026**. That date is on the banner; the demo
never claims to be live.

The live database is ~224 MB across 1.15M rows and every quarter since 2013 —
too large to commit, and more than a demo needs. The snapshot keeps every row
and every column of those four quarters, so the demo runs the same SQL the live
app does and the numbers on screen are real. One exception: `all_columns_raw`,
the raw XML each holding was parsed from, is nulled. It was 23 MB of the 33 and
nothing but the full CSV export reads it.

`holdings_ticker_index.json` travels beside the snapshot so search accepts
tickers (`NVDA`) and not only issuer names. Building that index means asking SEC
for its ticker reference, which the demo must never do, so it ships pre-built
and the API re-stamps its recorded mtime at startup.

### Refreshing the snapshot

```bash
# Against a current live DuckDB (rebuild it first if it is stale:
# python -m src.cli.process_historical_13f full --yes)
python -m demo.freeze_demo_data                 # 4 quarters, default paths
python -m demo.freeze_demo_data --quarters 6    # more history, larger file

git add demo/fixtures && git commit
bash deploy-site.sh
```

The script prints the row counts and the size, and writes
`demo/fixtures/13f_demo.meta.json` — which is where the banner's "filings up
to …" date comes from, so it is never typed by hand.

## Running it locally

Two processes, as in normal development, plus the demo environment:

```bash
# API
DEMO_MODE=true \
DEMO_SESSION_SECRET=anything-long-for-dev \
DEMO_PUBLIC_URL=http://localhost:5173 \
F8_DASHBOARD_DB=demo/fixtures/13f_demo.duckdb \
python -m src.api

# UI
npm --prefix frontend run dev
```

There is no SMTP server on a dev machine, so `request-access` will fail at the
send. Either point `DEMO_SMTP_*` at a real mailbox, or patch
`src.api.demo_mail.send_access_link` to print the link — which is what the
capture runner in `shotkit.demo.config.mjs` documents.

## Configuration

Everything is an environment variable. On the server they live in
`/opt/sites/13f/.env` (0600, root-owned) and in `.deploy/compose.yml` for the
non-secret ones. Nothing here belongs in git.

| Variable | Default | What it does |
| --- | --- | --- |
| `DEMO_MODE` | unset | **The kill switch.** Unset or false: no gate, no demo routes, the API reads the live database. Everything below is ignored. |
| `DEMO_SESSION_SECRET` | — | HMAC key for both token kinds. Required; no default on purpose. Change it and every outstanding link and session dies. |
| `DEMO_PUBLIC_URL` | — | Where the emailed link points. Required. |
| `F8_DASHBOARD_DB` | the live DuckDB | Which database to read. The demo points it at the snapshot. |
| `F8_STATIC_DIR` | unset | Serve the built React bundle from the API process. Set only in the container, where one port has to answer both. |
| `DEMO_SESSION_TTL_MINUTES` | 240 | How long a session lasts once the link is followed. |
| `DEMO_LINK_TTL_MINUTES` | 30 | How long an emailed link stays good. |
| `DEMO_LINKS_PER_IP_PER_HOUR` | 5 | Per-connection cap on access requests. |
| `DEMO_RESEND_COOLDOWN_SECONDS` | 60 | Wait before the same address can be mailed again. |
| `DEMO_DAILY_LINK_CAP` | 200 | **Global ceiling across everyone.** The one that stops a scripted afternoon turning the demo into a way of mailing strangers from this domain. |
| `DEMO_NOTIFY_EMAIL` | unset | Gets one line per access request. Optional. |
| `DEMO_SMTP_HOST` | — | SMTP server. Required. |
| `DEMO_SMTP_PORT` | 587 | 465 for implicit TLS, anything else uses STARTTLS. |
| `DEMO_SMTP_USER` / `DEMO_SMTP_PASS` | — | Mailbox credentials. Required. |
| `DEMO_MAIL_FROM` | `DEMO_SMTP_USER` | The `From:` address. |

With `DEMO_MODE` on and any of the required ones missing, **the app refuses to
start**. That is deliberate: the deploy's health check only asks whether the
server answers, so a demo with no working mail would go live looking fine and
turn every visitor away at the gate.

## Turning it off

```bash
ssh root@77.42.70.26 "sed -i 's/^DEMO_MODE=.*/DEMO_MODE=false/' /opt/sites/13f/.env"
# or take the whole site down:
bash "$HOME/.claude/skills/hetzner-site/bin/site-remove.sh" 13f
```

Then remove the `demo` block from the landing page's `src/_data/builds.js` (both
languages) so the card stops pointing at a dead link, and set `status` to
`"retired"` in `demo/demo.json`.

## Deploying

`.deploy/` holds the whole deployment: one container, built from
`.deploy/Dockerfile`, in which a Node stage builds the React bundle and a Python
stage runs FastAPI serving both it and the API. The edge proxies one hostname to
one port, which is why the deployed demo is one process where local development
is two.

```bash
bash deploy-site.sh --dry-run   # review
bash deploy-site.sh             # ship
bash deploy-site.sh --rollback  # back to the last good commit
```

The container runs read-only with the writable paths mounted as tmpfs, drops
all capabilities, and publishes no host port — the only way in is through the
shared nginx edge, which terminates TLS.

> Not to be confused with the repo's own `deploy.sh`, which deploys the **live
> screener and poller** to the same box. Different thing, different service.
