// Screenshot config for the PUBLIC DEMO of the 13F screener.
//
// Separate from shotkit.config.mjs on purpose: that one captures the live
// dashboard against the full 1.15M-row DuckDB, this one captures what a
// stranger actually sees — the email gate, the demo banner, and the same four
// views over the frozen snapshot in demo/fixtures/.
//
// The builds page requires captures of the demo, not of the authenticated app,
// so these are the ones that belong on the card.
//
// Bring the demo up first. There is no SMTP server on a dev machine, so the
// API is started through a scratchpad wrapper that writes the access link to a
// file instead of mailing it; LINK_FILE below points at that file. On the real
// deploy the same link goes to the visitor's inbox and nothing else differs.
//
//   API_SERVER_PORT=9004 DEMO_MODE=true DEMO_SESSION_SECRET=… \
//     DEMO_PUBLIC_URL=http://localhost:5180 \
//     F8_DASHBOARD_DB=demo/fixtures/13f_demo.duckdb \
//     python <scratchpad>/run_demo_local.py
//   F8_API_PROXY_TARGET=http://127.0.0.1:9004 npx vite --port 5180 --strictPort
//
// The snapshot is a fifth of the live database, so aggregations that took tens
// of seconds on the live DB settle in a few here. The waits below are still
// generous — a skeleton row screenshots perfectly happily.

import fs from "node:fs";

const BASE = "http://localhost:5180";
const LINK_FILE = process.env.DEMO_LINK_FILE || "";

// A fresh address per run: the gate refuses a second link to the same inbox
// inside the cooldown, so reusing one would make every shot after the first
// capture an error state.
const visitorEmail = () => `visitor+${Date.now()}@example.com`;

// Walk the gate the way a visitor does — ask for a link, then follow it. The
// session cookie it sets is what every later shot rides on.
async function enterDemo(page) {
  await page.goto(BASE + "/", { waitUntil: "networkidle" });

  // The browser context can carry a session cookie over from an earlier shot,
  // in which case there is no gate to walk and the dashboard is already up.
  const gate = page.getByLabel("Your email");
  if (!(await gate.isVisible().catch(() => false))) {
    await page.waitForSelector("table", { timeout: 120_000 });
    return;
  }

  const before = fs.existsSync(LINK_FILE) ? fs.readFileSync(LINK_FILE, "utf8") : "";
  await gate.fill(visitorEmail());
  await page.getByRole("button", { name: /email me the link/i }).click();
  await page.getByText(/check your inbox/i).waitFor({ timeout: 30_000 });

  let link = before;
  for (let i = 0; i < 40 && link === before; i += 1) {
    await page.waitForTimeout(250);
    link = fs.existsSync(LINK_FILE) ? fs.readFileSync(LINK_FILE, "utf8").trim() : before;
  }
  if (!link || link === before) throw new Error("no access link was written to " + LINK_FILE);

  await page.goto(link, { waitUntil: "networkidle" });
  await page.waitForSelector("table", { timeout: 120_000 });
}

async function settled(page, timeout = 120_000) {
  await page.waitForFunction(
    () => !document.querySelector('[class*="Skeleton-root"]'),
    null,
    { timeout },
  );
}

export default {
  baseUrl: BASE,
  viewport: { width: 1440, height: 900 },
  colorScheme: "light",
  outDir: ".shots-demo",

  shots: [
    {
      name: "01-demo-gate",
      shows: "The email gate: leave an address, get a link back — no account, no password",
      path: "/",
      waitFor: "input[type=email]",
      settleMs: 600,
    },
    {
      name: "02-demo-link-sent",
      shows: "The gate after asking: the link is on its way and good for thirty minutes",
      path: "/",
      async prepare(page) {
        await page.getByLabel("Your email").fill(visitorEmail());
        await page.getByRole("button", { name: /email me the link/i }).click();
        await page.getByText(/check your inbox/i).waitFor({ timeout: 30_000 });
        await page.waitForTimeout(400);
      },
      settleMs: 400,
    },
    {
      name: "03-demo-overview",
      shows: "Through the gate: the demo banner naming the snapshot date, over the latest filing per fund",
      path: "/",
      async prepare(page) {
        await enterDemo(page);
        await page.waitForTimeout(1200);
      },
      settleMs: 800,
    },
    {
      name: "04-demo-fund-analysis",
      shows: "One fund's workspace over the frozen snapshot: quarter picker and top positions by value",
      path: "/",
      async prepare(page) {
        await enterDemo(page);
        await page.getByText("Fund Analysis", { exact: true }).click();
        await page.waitForTimeout(2500);
        await settled(page);
        await page.waitForTimeout(1200);
      },
      settleMs: 800,
    },
    {
      name: "05-demo-consensus",
      shows: "Consensus accumulation across the four snapshot quarters: what the tracked funds bought together",
      path: "/",
      async prepare(page) {
        await enterDemo(page);
        await page.getByText("Consensus Trends", { exact: true }).click();
        await settled(page);
        await page.waitForTimeout(1500);
      },
      settleMs: 800,
    },
    {
      name: "06-demo-holdings-search",
      shows: "Ticker search across every tracked fund: who held NVIDIA in the snapshot, purchases, calls and puts apart",
      path: "/",
      async prepare(page) {
        await enterDemo(page);
        await page.getByText("Holdings Search", { exact: true }).click();
        await page.waitForTimeout(1200);
        await page
          .getByPlaceholder("e.g. apple, 037833100, ORAN, AAPL berkshire")
          .fill("NVDA");
        await page.getByRole("button", { name: /search/i }).click();
        await page.waitForSelector("table", { timeout: 120_000 });
        await settled(page);
        await page.waitForTimeout(1500);
      },
      settleMs: 800,
    },
  ],
};
