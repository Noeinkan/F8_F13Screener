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
 * Build a holdings-search deep link from a row's Issuer cell.
 * Used in tables (e.g. new / closed / share-change) that don't expose a Ticker.
 */
export const buildIssuerHoldingsSearchHref: CellLinkBuilder = (row) => {
  const issuer = row["Issuer"];
  if (issuer === null || issuer === undefined) return undefined;
  const text = String(issuer).trim();
  if (!text || SKIP_TOKENS.has(text.toLowerCase())) return undefined;
  return `/holdings-search?q=${encodeURIComponent(text)}`;
};

export const ISSUER_CELL_LINK: Record<string, CellLinkBuilder> = {
  Issuer: buildIssuerHoldingsSearchHref,
};

/**
 * Build a holdings-search deep link from a row's CUSIP cell.
 * CUSIPs are unique identifiers so they yield the most precise matches.
 */
export const buildCusipHoldingsSearchHref: CellLinkBuilder = (row) => {
  const cusip = row["CUSIP"];
  if (cusip === null || cusip === undefined) return undefined;
  const text = String(cusip).trim();
  if (!text || SKIP_TOKENS.has(text.toLowerCase())) return undefined;
  return `/holdings-search?q=${encodeURIComponent(text)}`;
};

export const CUSIP_CELL_LINK: Record<string, CellLinkBuilder> = {
  CUSIP: buildCusipHoldingsSearchHref,
};

/**
 * Combined link map for tables that expose both Ticker and Issuer/CUSIP.
 * Ticker is the primary entry point; Issuer and CUSIP remain clickable as fallbacks.
 */
export const HOLDINGS_SEARCH_CELL_LINKS: Record<string, CellLinkBuilder> = {
  Ticker: buildHoldingsSearchHref,
  Issuer: buildIssuerHoldingsSearchHref,
  CUSIP: buildCusipHoldingsSearchHref,
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
