// Screenshot config for the 13F screener dashboard.
//
// Notes for the next run:
//  * `npm start` runs the API with whatever `python` is on PATH, which on this
//    machine has no uvicorn. Start the two halves yourself instead:
//      .venv/Scripts/python.exe -m src.api      (API on :9001)
//      npm --prefix frontend run dev            (Vite on :5173)
//    then run shotkit without --serve.
//  * Everything in frame is public SEC 13F data out of the local DuckDB build —
//    fund names, CIKs and holdings are all filed documents. Nothing to mask on
//    those grounds.
//  * The sidebar footer DOES print the absolute path of the local database,
//    i.e. `C:\Users\<name>\…`. `hidePaths` strips those two lines before every
//    shot; the SPA re-renders the sidebar on navigation, so it has to run per
//    shot rather than once in `setup`.

// Drop the two sidebar lines that print local filesystem paths.
async function hidePaths(page) {
  await page.evaluate(() => {
    for (const el of document.querySelectorAll("div p, div div")) {
      const t = (el.textContent || "").trim();
      if (t.startsWith("DB live:") || t.startsWith("Read path:")) el.remove();
    }
  });
}

export default {
  baseUrl: "http://localhost:5173",
  viewport: { width: 1440, height: 900 },
  colorScheme: "light",

  shots: [
    {
      name: "01-overview",
      shows: "Database status and the latest filing per fund: raw 13F lines, CUSIP-normalised positions and portfolio value",
      path: "/",
      waitFor: "table",
      async prepare(page) {
        await page.waitForTimeout(1200);
        await hidePaths(page);
      },
      settleMs: 800,
    },
    {
      name: "02-fund-analysis",
      shows: "One fund's workspace: position changes between filings, sized by weight",
      path: "/",
      waitFor: "table",
      async prepare(page) {
        await page.getByText("Fund Analysis", { exact: true }).click();
        await page.waitForTimeout(2500);
        await hidePaths(page);
      },
      settleMs: 800,
    },
    {
      name: "03-consensus-trends",
      shows: "Consensus across the tracked funds: what they are collectively buying and selling",
      path: "/",
      waitFor: "table",
      async prepare(page) {
        await page.getByText("Consensus Trends", { exact: true }).click();
        // The cross-fund aggregation runs over a million holding rows; the
        // skeletons are still up at 3s. Wait on the chart, not on a timeout.
        await page.waitForFunction(
          () => !document.querySelector('[class*="Skeleton-root"]'),
          null, { timeout: 90_000 }
        );
        await page.waitForTimeout(1500);
        await hidePaths(page);
      },
      settleMs: 800,
    },
    {
      name: "04-holdings-search",
      shows: "Holdings search: every tracked fund holding one security, across filings",
      path: "/",
      // No table exists until a search is submitted, so this shot cannot use
      // `waitFor: table` the way the others do.
      async prepare(page) {
        await page.getByText("Holdings Search", { exact: true }).click();
        await page.waitForTimeout(1200);
        await page.getByPlaceholder("e.g. apple, 037833100, ORAN, AAPL berkshire").fill("NVDA");
        await page.getByRole("button", { name: /search/i }).click();
        await page.waitForSelector("table", { timeout: 60_000 });
        // The table renders as skeleton rows first; searching 1.15M holding
        // rows takes tens of seconds, so wait for the skeletons to clear.
        await page.waitForFunction(
          () => !document.querySelector('[class*="Skeleton-root"]'),
          null, { timeout: 180_000 }
        );
        await page.waitForTimeout(1500);
        await hidePaths(page);
      },
      settleMs: 800,
    },
  ],
};
