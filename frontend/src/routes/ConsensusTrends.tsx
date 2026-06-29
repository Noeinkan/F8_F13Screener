import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { MultiSelect, Paper, Select, SimpleGrid, Text } from "@mantine/core";
import { apiGet } from "@/api/client";
import { HorizontalBarChart } from "@/components/Charts";
import { DataTable } from "@/components/DataTable";
import { ExportLink } from "@/components/ExportLink";
import { KpiGrid } from "@/components/KpiCard";
import { SectionHeader } from "@/components/SectionHeader";
import { KpiLoading, ChartLoading } from "@/components/LoadingState";
import { TICKER_CELL_LINK } from "@/utils/cellLinks";

type Leaderboard = {
  chart: { title: string; x: number[]; y: string[] };
  rows: Record<string, unknown>[];
  columns?: string[];
};

type ConsensusResponse = {
  metadata: {
    funds: number;
    quarters: string[];
    latest_quarter: string;
    movement_rows: number;
    value_multiplier_summary?: string;
  };
  accumulation: Leaderboard;
  distribution: Leaderboard;
  weight_growth: Leaderboard;
  latest_consensus: Leaderboard;
};

type LeaderboardConfig = {
  key: "accumulation" | "distribution" | "weight_growth" | "latest_consensus";
  title: string;
  description: string;
  columnOrder: string[];
  downloadName: string;
};

const LEADERBOARD_CONFIGS: LeaderboardConfig[] = [
  {
    key: "accumulation",
    title: "Consensus accumulation",
    description: "Positions opened or increased by multiple funds across the selected window.",
    columnOrder: [
      "Ticker",
      "Issuer",
      "CUSIP",
      "Funds Buying",
      "Funds Opening",
      "Funds Increasing",
      "Transitions",
      "Share Delta",
      "Value Delta",
      "Avg Weight Delta",
    ],
    downloadName: "consensus_accumulation",
  },
  {
    key: "distribution",
    title: "Consensus distribution",
    description: "Positions reduced or closed by multiple funds across the selected window.",
    columnOrder: [
      "Ticker",
      "Issuer",
      "CUSIP",
      "Funds Selling",
      "Funds Closing",
      "Funds Decreasing",
      "Transitions",
      "Share Delta",
      "Value Delta",
      "Avg Weight Delta",
    ],
    downloadName: "consensus_distribution",
  },
  {
    key: "weight_growth",
    title: "Growing portfolio weight",
    description:
      "Positions becoming larger parts of portfolios, including cases where share count was flat but portfolio weight rose.",
    columnOrder: [
      "Ticker",
      "Issuer",
      "CUSIP",
      "Funds_With_Weight_Growth",
      "Avg Weight Delta",
      "Median Weight Delta",
      "Share Delta",
      "Value Delta",
    ],
    downloadName: "portfolio_weight_growth",
  },
  {
    key: "latest_consensus",
    title: "Crowded and emerging consensus",
    description: "Latest-quarter ownership breadth, holder-count changes, and aggregate exposure.",
    columnOrder: [
      "Ticker",
      "Issuer",
      "CUSIP",
      "Latest_Holders",
      "Previous_Holders",
      "Holder Delta",
      "Total Shares",
      "Total Value",
      "Avg Portfolio Weight",
    ],
    downloadName: "latest_consensus",
  },
];

function buildExportHref(
  section: string,
  params: { lookback: string; minFunds: string; topN: string; selectedFunds: string[] },
): string {
  const search = new URLSearchParams({
    section,
    lookback_quarters: params.lookback,
    min_funds: params.minFunds,
    top_n: params.topN,
  });
  if (params.selectedFunds.length) {
    search.set("funds", params.selectedFunds.join(","));
  }
  return `/api/consensus/trends/export?${search.toString()}`;
}

function LeaderboardSection({
  config,
  section,
  exportHref,
  onPointClick,
}: {
  config: LeaderboardConfig;
  section: Leaderboard;
  exportHref: string;
  onPointClick: (label: string) => void;
}) {
  const columns = useMemo(() => {
    if (section.columns?.length) return section.columns;
    return section.rows[0] ? Object.keys(section.rows[0]) : [];
  }, [section.columns, section.rows]);

  return (
    <Paper withBorder p="md" radius="md" bg="white" mb="lg">
      <SectionHeader
        title={config.title}
        caption={config.description}
        right={
          <ExportLink
            href={exportHref}
            label="Download CSV"
            fileName={`f8_13f_${config.downloadName}.csv`}
          />
        }
      />
      <HorizontalBarChart chart={section.chart} onPointClick={onPointClick} />
      <DataTable
        columns={columns}
        columnOrder={config.columnOrder}
        rows={section.rows}
        maxHeight={420}
        stickyHeader
        emptyMessage="No rows match the current filters."
        cellLinks={TICKER_CELL_LINK}
      />
    </Paper>
  );
}

export function ConsensusTrendsPage() {
  const navigate = useNavigate();
  const [lookback, setLookback] = useState("4");
  const [minFunds, setMinFunds] = useState("2");
  const [topN, setTopN] = useState("20");
  const [selectedFunds, setSelectedFunds] = useState<string[]>([]);

  const goToHoldingsSearch = useMemo(
    () => (label: string) => {
      const text = label.trim();
      if (!text || text.toLowerCase() === "unknown") return;
      navigate(`/holdings-search?q=${encodeURIComponent(text)}`);
    },
    [navigate],
  );

  const fundsQuery = useQuery({
    queryKey: ["funds"],
    queryFn: () => apiGet<{ funds: string[] }>("/api/funds"),
  });

  const trendsQuery = useQuery({
    queryKey: ["consensus", lookback, minFunds, topN, selectedFunds.join(",")],
    queryFn: () => {
      const params = new URLSearchParams({
        lookback_quarters: lookback,
        min_funds: minFunds,
        top_n: topN,
      });
      if (selectedFunds.length) params.set("funds", selectedFunds.join(","));
      return apiGet<ConsensusResponse>(`/api/consensus/trends?${params.toString()}`);
    },
  });

  const data = trendsQuery.data;
  const exportParams = { lookback, minFunds, topN, selectedFunds };

  const windowCaption = useMemo(() => {
    if (!data?.metadata.quarters.length) return null;
    const quarters = data.metadata.quarters;
    const multiplier = data.metadata.value_multiplier_summary ?? "x1";
    return `Window: ${quarters[0]} through ${quarters[quarters.length - 1]}. Value displays are auto-normalized by accession (${multiplier}).`;
  }, [data?.metadata.quarters, data?.metadata.value_multiplier_summary]);

  return (
    <div>
      <Text size="sm" c="dimmed" mb="md">
        Cross-fund 13F movement, ownership, and portfolio-weight patterns across recent filing quarters.
      </Text>

      <Paper withBorder p="md" radius="md" bg="white" mb="lg">
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
          <Select
            label="Window"
            data={["2", "4", "6", "8"]}
            value={lookback}
            onChange={(value) => setLookback(value ?? "4")}
          />
          <Select
            label="Minimum funds"
            data={Array.from({ length: 10 }, (_, index) => String(index + 1))}
            value={minFunds}
            onChange={(value) => setMinFunds(value ?? "2")}
          />
          <Select
            label="Rows"
            data={["10", "15", "20", "25", "30", "35", "40", "45", "50"]}
            value={topN}
            onChange={(value) => setTopN(value ?? "20")}
          />
          <MultiSelect
            label="Fund subset"
            data={fundsQuery.data?.funds ?? []}
            value={selectedFunds}
            onChange={setSelectedFunds}
            placeholder="All tracked funds"
            searchable
          />
        </SimpleGrid>
      </Paper>

      {trendsQuery.isLoading && !data ? (
        <>
          <KpiLoading count={4} />
          {LEADERBOARD_CONFIGS.map((config) => (
            <Paper key={config.key} withBorder p="md" radius="md" bg="white" mb="lg">
              <SectionHeader title={config.title} caption={config.description} />
              <ChartLoading />
              <DataTable
                columns={[]}
                rows={[]}
                columnOrder={config.columnOrder}
                loading
                loadingRows={5}
                loadingColumns={config.columnOrder.length}
                maxHeight={420}
                stickyHeader
                emptyMessage="No rows match the current filters."
              />
            </Paper>
          ))}
        </>
      ) : null}

      {data ? (
        <>
          <KpiGrid
            items={[
              { label: "Funds analyzed", value: data.metadata.funds.toLocaleString() },
              { label: "Quarters", value: data.metadata.quarters.length.toLocaleString() },
              { label: "Latest quarter", value: data.metadata.latest_quarter },
              { label: "Position transitions", value: data.metadata.movement_rows.toLocaleString() },
            ]}
          />

          {windowCaption ? (
            <Text size="sm" c="dimmed" mb="lg">
              {windowCaption}
            </Text>
          ) : null}

          {LEADERBOARD_CONFIGS.map((config) => (
            <LeaderboardSection
              key={config.key}
              config={config}
              section={data[config.key]}
              exportHref={buildExportHref(config.key, exportParams)}
              onPointClick={goToHoldingsSearch}
            />
          ))}
        </>
      ) : null}
    </div>
  );
}
