import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Anchor, Button, Group, Paper, Text, TextInput } from "@mantine/core";
import { apiGet } from "@/api/client";
import { buildF2TickerUrl } from "@/config/externalLinks";
import { DataTable } from "@/components/DataTable";
import { ExportLink } from "@/components/ExportLink";
import { KpiGrid } from "@/components/KpiCard";
import { SectionHeader } from "@/components/SectionHeader";
import { KpiLoading } from "@/components/LoadingState";
import { formatDateValue } from "@/utils/dateFormat";

type HoldingsSearchResponse = {
  query: string;
  total_matches: number;
  funds_count: number;
  issuers_count: number;
  latest_filing: string | null;
  value_multiplier_summary?: string | null;
  latest_by_fund: Record<string, unknown>[];
  all_rows: Record<string, unknown>[];
  truncated: boolean;
};

const LATEST_BY_FUND_COLUMN_ORDER = [
  "Ticker",
  "Type",
  "Issuer",
  "Fund",
  "Filing Date",
  "Put/Call",
  "Shares",
  "Value",
];

const ALL_ROWS_COLUMN_ORDER = [
  "Ticker",
  "Type",
  "Issuer",
  "CUSIP",
  "Fund",
  "Filing Date",
  "Put/Call",
  "Shares",
  "Value",
];

function safeFileToken(value: string): string {
  const token = value.trim().replace(/[^0-9A-Za-z._-]+/g, "_").replace(/^_+|_+$/g, "");
  return token || "search";
}

export function HoldingsSearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const [queryText, setQueryText] = useState(initialQuery);
  const [submitted, setSubmitted] = useState(initialQuery);

  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    if (q && q !== submitted) {
      setQueryText(q);
      setSubmitted(q);
    }
  }, [searchParams, submitted]);

  const trimmedSubmitted = submitted.trim();
  const trimmedCurrent = queryText.trim();

  const searchQuery = useQuery({
    queryKey: ["holdings-search", trimmedSubmitted],
    queryFn: () =>
      apiGet<HoldingsSearchResponse>(`/api/holdings/search?q=${encodeURIComponent(trimmedSubmitted)}`),
    enabled: trimmedSubmitted.length > 0,
  });

  const data = searchQuery.data;

  const uniqueTicker = useMemo<string | null>(() => {
    if (!data?.latest_by_fund?.length) return null;
    const skip = new Set(["", "-", "unknown", "n/a", "none"]);
    const set = new Set<string>();
    for (const row of data.latest_by_fund) {
      const raw = row["Ticker"];
      if (raw === null || raw === undefined) continue;
      const text = String(raw).trim();
      if (!text || skip.has(text.toLowerCase())) continue;
      set.add(text.toUpperCase());
    }
    if (set.size !== 1) return null;
    return set.values().next().value ?? null;
  }, [data]);

  const latestColumns = useMemo(() => {
    const rows = data?.latest_by_fund ?? [];
    return rows[0] ? Object.keys(rows[0]) : [];
  }, [data?.latest_by_fund]);

  const allRowsColumns = useMemo(() => {
    const rows = data?.all_rows ?? [];
    return rows[0] ? Object.keys(rows[0]) : [];
  }, [data?.all_rows]);

  const exportFileName = useMemo(() => `f8_13f_search_${safeFileToken(trimmedSubmitted)}.csv`, [trimmedSubmitted]);
  const exportHref = trimmedSubmitted
    ? `/api/holdings/search/export?q=${encodeURIComponent(trimmedSubmitted)}`
    : "";

  const handleSearch = () => {
    const next = trimmedCurrent;
    if (!next) return;
    setSubmitted(next);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("q", next);
    setSearchParams(nextParams, { replace: true });
  };

  return (
    <div>
      <Paper withBorder p="md" radius="md" bg="white" mb="lg">
        <Group align="flex-end" gap="md" wrap="wrap">
          <TextInput
            style={{ flexGrow: 1, minWidth: 280 }}
            label="Search by issuer, CUSIP, fund, or ticker"
            placeholder="e.g. apple, 037833100, ORAN, AAPL berkshire"
            value={queryText}
            onChange={(event) => setQueryText(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && trimmedCurrent) handleSearch();
            }}
          />
          <Button onClick={handleSearch} disabled={!trimmedCurrent}>
            Search
          </Button>
        </Group>
        <Text size="sm" c="dimmed" mt="xs">
          Ticker terms match against the holdings index. Multiple terms narrow
          results. CUSIP search ignores punctuation.
        </Text>
      </Paper>

      {!submitted ? <Text>Enter a search term to begin.</Text> : null}
      {submitted && searchQuery.isLoading ? (
        <>
          <KpiLoading count={4} />
          <Paper withBorder p="md" radius="md" bg="white" mb="lg">
            <SectionHeader title="Who holds it today (latest filing per fund)" />
            <DataTable
              columns={[]}
              rows={[]}
              columnOrder={LATEST_BY_FUND_COLUMN_ORDER}
              loading
              loadingRows={5}
              loadingColumns={LATEST_BY_FUND_COLUMN_ORDER.length}
              maxHeight={420}
              stickyHeader
            />
          </Paper>
          <Paper withBorder p="md" radius="md" bg="white">
            <SectionHeader title="All matching rows" />
            <DataTable
              columns={[]}
              rows={[]}
              columnOrder={ALL_ROWS_COLUMN_ORDER}
              loading
              loadingRows={5}
              loadingColumns={ALL_ROWS_COLUMN_ORDER.length}
              maxHeight={420}
              stickyHeader
            />
          </Paper>
        </>
      ) : null}
      {data && Number(data.total_matches) === 0 ? (
        <Text>No results found for &ldquo;{trimmedSubmitted}&rdquo;.</Text>
      ) : null}

      {data && Number(data.total_matches) > 0 ? (
        <>
          <KpiGrid
            items={[
              { label: "Matching rows", value: Number(data.total_matches).toLocaleString() },
              { label: "Funds", value: Number(data.funds_count).toLocaleString() },
              { label: "Issuers", value: Number(data.issuers_count).toLocaleString() },
              { label: "Latest filing", value: formatDateValue(data.latest_filing) },
            ]}
          />

          {data.value_multiplier_summary ? (
            <Text size="sm" c="dimmed" mb="md">
              Value displays are auto-normalized by accession using implied per-share prices
              (multipliers: {data.value_multiplier_summary}).
            </Text>
          ) : null}

          <Paper withBorder p="md" radius="md" bg="white" mb="lg">
            <SectionHeader
              title="Who holds it today (latest filing per fund)"
              right={
                <Group gap="md">
                  {uniqueTicker ? (
                    <Anchor
                      href={buildF2TickerUrl(uniqueTicker)}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: "0.85rem", fontWeight: 600 }}
                    >
                      Open in SearchForAlpha
                    </Anchor>
                  ) : null}
                  <ExportLink href={exportHref} label="Download CSV results" fileName={exportFileName} />
                </Group>
              }
            />
            <DataTable
              columns={latestColumns}
              columnOrder={LATEST_BY_FUND_COLUMN_ORDER}
              rows={data.latest_by_fund}
              maxHeight={420}
              stickyHeader
            />
          </Paper>

          <Paper withBorder p="md" radius="md" bg="white">
            <SectionHeader title="All matching rows" />
            {data.truncated ? (
              <Text size="sm" c="dimmed" mb="sm">
                Showing first 1,000 rows. Download the CSV for all {Number(data.total_matches).toLocaleString()}{" "}
                matches.
              </Text>
            ) : null}
            <DataTable
              columns={allRowsColumns}
              columnOrder={ALL_ROWS_COLUMN_ORDER}
              rows={data.all_rows}
              maxHeight={420}
              stickyHeader
            />
          </Paper>
        </>
      ) : null}
    </div>
  );
}