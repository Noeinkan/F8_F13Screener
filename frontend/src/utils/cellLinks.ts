import type { CellLinkBuilder } from "@/components/DataTable";

const SKIP_TOKENS = new Set(["", "-", "unknown", "n/a", "none"]);

/**
 * Build a holdings-search deep link from a row's Ticker cell.
 * Returns undefined when the ticker is missing/placeholder so no link is rendered.
 */
export const buildHoldingsSearchHref: CellLinkBuilder = (row) => {
  const ticker = row["Ticker"];
  if (ticker === null || ticker === undefined) return undefined;
  const text = String(ticker).trim();
  if (!text || SKIP_TOKENS.has(text.toLowerCase())) return undefined;
  return `/holdings-search?q=${encodeURIComponent(text)}`;
};

export const TICKER_CELL_LINK: Record<string, CellLinkBuilder> = {
  Ticker: buildHoldingsSearchHref,
};

/**
 * Build a fund-analysis deep link from a row's Fund cell.
 * Returns undefined when the fund name is missing/placeholder so no link is rendered.
 */
export const buildFundAnalysisHref: CellLinkBuilder = (row) => {
  const fund = row["Fund"];
  if (fund === null || fund === undefined) return undefined;
  const text = String(fund).trim();
  if (!text || SKIP_TOKENS.has(text.toLowerCase())) return undefined;
  return `/fund-analysis?fund=${encodeURIComponent(text)}`;
};

export const FUND_CELL_LINK: Record<string, CellLinkBuilder> = {
  Fund: buildFundAnalysisHref,
};
