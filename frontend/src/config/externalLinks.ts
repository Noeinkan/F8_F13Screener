// Frontend-only config for external service URLs.
const F2_BASE_URL_FALLBACK = "http://77.42.70.26:8060";
const KOFI_BASE_URL = "https://ko-fi.com";
const KOFI_USERNAME_FALLBACK = "noeinkan";

export const F2_SEARCHFORALPHA_BASE_URL: string =
  (import.meta.env.VITE_F2_BASE_URL as string | undefined)?.replace(/\/+$/, "") ||
  F2_BASE_URL_FALLBACK;

export function buildF2TickerUrl(ticker: string): string {
  return `${F2_SEARCHFORALPHA_BASE_URL}/ticker/${encodeURIComponent(ticker)}`;
}

export const KOFI_URL: string =
  (import.meta.env.VITE_KOFI_URL as string | undefined)?.replace(/\/+$/, "") ||
  `${KOFI_BASE_URL}/${KOFI_USERNAME_FALLBACK}`;
