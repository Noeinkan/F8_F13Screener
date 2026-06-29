import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Group, Paper, SimpleGrid, Text, TextInput } from "@mantine/core";
import { apiGet } from "@/api/client";
import { BarChart, LineChart } from "@/components/Charts";
import { DataTable } from "@/components/DataTable";
import { KpiGrid } from "@/components/KpiCard";
import { SectionHeader } from "@/components/SectionHeader";
import { ExportLink } from "@/components/ExportLink";
import { AlertBanner } from "@/components/AlertBanner";
import { ChartLoading, KpiLoading } from "@/components/LoadingState";
import { formatDateValue } from "@/utils/dateFormat";
import { FUND_CELL_LINK, TICKER_CELL_LINK } from "@/utils/cellLinks";

type OverviewFundsResponse = {
  has_data: boolean;
  has_portfolio_values: boolean;
  summary: {
    positions: number;
    filings: number;
    funds: number;
    latest_filing_date: string;
  };
  recent_activity: {
    recent_filings: number;
    recent_funds: number;
  };
  funds: Record<string, unknown>[];
  chart: { title: string; x: string[]; y: number[]; y_label?: string };
  value_multiplier_summary?: string | null;
};

type FeedStatisticsRow = {
  total_checked?: number | string | null;
  matched?: number | string | null;
  filtered?: number | string | null;
  [key: string]: unknown;
};

type FeedStatisticsResponse = {
  available: boolean;
  row: FeedStatisticsRow | null;
};

const FUNDS_COLUMN_ORDER = [
  "Fund",
  "Quarters",
  "Latest Filing",
  "Raw 13F Lines",
  "Normalized Positions",
  "Distinct CUSIPs",
  "Portfolio Value",
];

const RECENT_FILINGS_COLUMN_ORDER = [
  "Fund",
  "Filing Date",
  "Accession",
  "Raw 13F Lines",
  "Normalized Positions",
  "Distinct CUSIPs",
];

const TOP_HELD_COLUMN_ORDER = [
  "Ticker",
  "Type",
  "Issuer",
  "CUSIP",
  "Put/Call",
  "Funds Holding It",
];

function toCount(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function OverviewPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState("");

  const fundsQuery = useQuery({
    queryKey: ["overview-funds", filter],
    queryFn: () => apiGet<OverviewFundsResponse>(`/api/overview/funds?filter=${encodeURIComponent(filter)}`),
  });

  const timelineQuery = useQuery({
    queryKey: ["overview-timeline"],
    queryFn: () => apiGet<{ rows: { Month: string; Filings: number }[] }>("/api/overview/filings-timeline"),
  });

  const recentQuery = useQuery({
    queryKey: ["overview-recent"],
    queryFn: () => apiGet<{ rows: Record<string, unknown>[] }>("/api/overview/recent-filings"),
  });

  const topHeldQuery = useQuery({
    queryKey: ["overview-top-held"],
    queryFn: () => apiGet<{ rows: Record<string, unknown>[] }>("/api/overview/top-held"),
  });

  const statsQuery = useQuery({
    queryKey: ["admin-statistics"],
    queryFn: () => apiGet<FeedStatisticsResponse>("/api/admin/statistics"),
  });

  const data = fundsQuery.data;

  const fundColumns = useMemo(() => {
    if (!data?.funds?.length) return [];
    return Object.keys(data.funds[0]);
  }, [data?.funds]);

  const recentColumns = useMemo(() => {
    const rows = recentQuery.data?.rows ?? [];
    return rows[0] ? Object.keys(rows[0]) : [];
  }, [recentQuery.data]);

  const topHeldColumns = useMemo(() => {
    const rows = topHeldQuery.data?.rows ?? [];
    return rows[0] ? Object.keys(rows[0]) : [];
  }, [topHeldQuery.data]);

  const timelineChart = useMemo(() => {
    const rows = timelineQuery.data?.rows ?? [];
    return {
      title: "Filings stored per month",
      x: rows.map((row) => String(row.Month)),
      y: rows.map((row) => Number(row.Filings ?? 0)),
    };
  }, [timelineQuery.data]);

  const feedStats = statsQuery.data;
  const feedStatsRow = feedStats?.row ?? null;
  const feedChecked = toCount(feedStatsRow?.total_checked);
  const feedMatched = toCount(feedStatsRow?.matched);
  const feedFiltered = toCount(feedStatsRow?.filtered);
  const hasFeedStats =
    feedStats?.available === true && (feedChecked > 0 || feedMatched > 0 || feedFiltered > 0);

  const fundsLoading = fundsQuery.isLoading;
  const recentLoading = recentQuery.isLoading;
  const topHeldLoading = topHeldQuery.isLoading;
  const timelineLoading = timelineQuery.isLoading;

  if (fundsLoading && !data) {
    return (
      <div>
        <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={6}>
          13F database status
        </Text>
        <KpiLoading count={5} />
        <Paper withBorder p="md" radius="md" bg="white" mb="lg">
          <SectionHeader
            title="Latest filing per fund"
            caption="For each fund, we show only the latest available filing, with raw row count and CUSIP-normalized count. Select a row to open the fund workspace."
          />
          <DataTable
            columns={[]}
            rows={[]}
            columnOrder={FUNDS_COLUMN_ORDER}
            loading
            loadingRows={6}
            maxHeight={420}
            stickyHeader
          />
        </Paper>
        <SimpleGrid cols={{ base: 1, md: 2 }} mb="lg">
          <ChartLoading title="Top 20 funds" />
          <ChartLoading title="Filings stored per month" />
        </SimpleGrid>
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          <Paper withBorder p="md" radius="md" bg="white">
            <SectionHeader title="Most recent filings" />
            <DataTable
              columns={[]}
              rows={[]}
              columnOrder={RECENT_FILINGS_COLUMN_ORDER}
              loading
              loadingRows={5}
              maxHeight={360}
            />
          </Paper>
          <Paper withBorder p="md" radius="md" bg="white">
            <SectionHeader title="Most common holdings today" />
            <DataTable
              columns={[]}
              rows={[]}
              columnOrder={TOP_HELD_COLUMN_ORDER}
              loading
              loadingRows={5}
              maxHeight={360}
            />
          </Paper>
        </SimpleGrid>
      </div>
    );
  }

  if (!data?.has_data) {
    return <Text>No data in the database yet.</Text>;
  }

  const recentFunds = data.recent_activity.recent_funds;
  const recentFilings = data.recent_activity.recent_filings;

  return (
    <div>
      <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={6}>
        13F database status
      </Text>

      <KpiGrid
        items={[
          { label: "Holding rows", value: data.summary.positions.toLocaleString() },
          { label: "13F filings", value: data.summary.filings.toLocaleString() },
          { label: "Covered funds", value: data.summary.funds.toLocaleString() },
          { label: "Latest filing", value: formatDateValue(data.summary.latest_filing_date) },
          { label: "Recent filings", value: recentFilings.toLocaleString() },
        ]}
      />

      {recentFunds > 0 ? (
        <Text size="sm" c="dimmed" mb="md">
          Funds with at least one filing in the last ~120 days: {recentFunds.toLocaleString()}
        </Text>
      ) : null}

      {data.has_portfolio_values ? (
        <AlertBanner variant="success" title="Portfolio values available">
          Fund rankings and charts now use the latest valued filing.
        </AlertBanner>
      ) : (
        <AlertBanner variant="warning" title="Portfolio values not available">
          <code>value_usd</code> / <code>value_x1000</code> are empty for the current database. This overview
          therefore shows useful signals based on filings, coverage, and normalized positions, which are the
          available data.
        </AlertBanner>
      )}

      {hasFeedStats ? (
        <Text size="sm" c="dimmed" mb="md">
          Feed monitor stats: checked {feedChecked.toLocaleString()} | matched{" "}
          {feedMatched.toLocaleString()} | filtered {feedFiltered.toLocaleString()}
        </Text>
      ) : null}

      <Paper withBorder p="md" radius="md" bg="white" mb="lg">
        <SectionHeader
          title="Latest filing per fund"
          caption="For each fund, we show only the latest available filing, with raw row count and CUSIP-normalized count. Select a row to open the fund workspace."
          right={
            <Group gap="md">
              <ExportLink
                href="/api/overview/exports/full"
                label="Export full holdings CSV"
                fileName="f8_13f_all_holdings.csv"
              />
              <ExportLink
                href="/api/overview/exports/latest"
                label="Export latest snapshot CSV"
                fileName="f8_13f_latest_snapshot.csv"
              />
            </Group>
          }
        />
        <TextInput
          label="Filter fund"
          placeholder="e.g. AQR, Berkshire, Appaloosa"
          value={filter}
          onChange={(event) => setFilter(event.currentTarget.value)}
          mb="md"
        />
        {data.has_portfolio_values && data.value_multiplier_summary ? (
          <Text size="sm" c="dimmed" mb="sm">
            Portfolio values are auto-normalized by filing accession using implied per-share prices
            (multipliers: {data.value_multiplier_summary}).
          </Text>
        ) : null}
        <DataTable
          columns={fundColumns}
          columnOrder={FUNDS_COLUMN_ORDER}
          rows={data.funds}
          maxHeight={420}
          stickyHeader
          loading={fundsLoading}
          cellLinks={FUND_CELL_LINK}
          onRowClick={(row) => {
            const fund = String(row.Fund ?? "");
            if (fund) navigate(`/fund-analysis?fund=${encodeURIComponent(fund)}`);
          }}
        />
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }} mb="lg">
        <Paper withBorder p="md" radius="md" bg="white">
          <BarChart
            chart={data.chart}
            loading={fundsLoading && !data.chart?.x?.length}
            onPointClick={(label) => {
              const text = label.trim();
              if (text) navigate(`/fund-analysis?fund=${encodeURIComponent(text)}`);
            }}
          />
        </Paper>
        <Paper withBorder p="md" radius="md" bg="white">
          <LineChart chart={timelineChart} loading={timelineLoading && !timelineChart.x.length} />
        </Paper>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
          <Paper withBorder p="md" radius="md" bg="white">
            <SectionHeader title="Most recent filings" />
            <DataTable
              columns={recentColumns}
              columnOrder={RECENT_FILINGS_COLUMN_ORDER}
              rows={recentQuery.data?.rows ?? []}
              maxHeight={360}
              loading={recentLoading}
              cellLinks={FUND_CELL_LINK}
            />
          </Paper>
          <Paper withBorder p="md" radius="md" bg="white">
            <SectionHeader title="Most common holdings today" />
            <DataTable
              columns={topHeldColumns}
              columnOrder={TOP_HELD_COLUMN_ORDER}
              rows={topHeldQuery.data?.rows ?? []}
              maxHeight={360}
              loading={topHeldLoading}
              cellLinks={TICKER_CELL_LINK}
            />
          </Paper>
      </SimpleGrid>
    </div>
  );
}
