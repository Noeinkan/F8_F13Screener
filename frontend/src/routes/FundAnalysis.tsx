import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Group,
  NumberInput,
  Paper,
  Radio,
  Select,
  SimpleGrid,
  Slider,
  Switch,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import { apiGet } from "@/api/client";
import {
  BarChart,
  GroupedBarChart,
  LanesChart,
  LineChart,
  SankeyChart,
} from "@/components/Charts";
import { DataTable } from "@/components/DataTable";
import { KpiGrid } from "@/components/KpiCard";
import { SectionHeader } from "@/components/SectionHeader";
import { ExportLink } from "@/components/ExportLink";
import { AlertBanner } from "@/components/AlertBanner";
import { ChartLoading, KpiLoading } from "@/components/LoadingState";
import { formatDateValue, formatAccessionLabel } from "@/utils/dateFormat";
import {
  HOLDINGS_SEARCH_CELL_LINKS,
  ISSUER_CELL_LINK,
} from "@/utils/cellLinks";

type AccessionLabel = {
  accession_number: string;
  filing_date: string;
  label: string;
};

type FundHeader = {
  fund: string;
  has_db_holdings: boolean;
  accessions: AccessionLabel[];
  latest_filing?: string | null;
  quarters?: number;
  current_positions?: number;
};

type SnapshotPayload = {
  empty?: boolean;
  value_multiplier?: number;
  filing_date?: string | null;
  metrics?: {
    raw_lines?: number;
    normalized_positions?: number;
    compression?: number;
  };
  chart?: { title: string; x: string[]; y: number[] };
  rows?: Record<string, unknown>[];
  position_insight?: {
    options?: string[];
    labels?: Record<string, string>;
    selected_key?: string;
    detail?: {
      metrics?: Record<string, string>;
      rows?: Record<string, unknown>[];
      captions?: string[];
      option_caption?: string;
      common_caption?: string;
    };
  };
};

type HistoryPayload = {
  history?: Record<string, unknown>[];
  transitions?: Array<{
    from_filing_date: string;
    to_filing_date: string;
    from_accession_number: string;
    to_accession_number: string;
    new_count: number;
    closed_count: number;
    increased_count: number;
    decreased_count: number;
  }>;
  transitions_chart?: {
    title: string;
    x: string[];
    series: { name: string; values: number[]; color?: string }[];
    y_label?: string;
  } | null;
  summary?: {
    quarters?: number;
    latest_filing?: string;
    current_positions?: number;
    positions_delta?: number;
    latest_value?: number | null;
    value_delta?: number | null;
    value_multiplier_summary?: string;
    latest_accession?: string;
  };
  charts?: {
    positions?: { title: string; x: string[]; y: number[]; labels?: string[] };
    value?: { title: string; x: string[]; y: number[]; labels?: string[] } | null;
    transitions?: Record<string, unknown>[];
  };
};

type CompareHighlight = {
  label: string;
  position_label: string;
  value: string;
  context: string;
};

type TopMovers = {
  rows?: Record<string, unknown>[];
  value_multiplier?: number;
};

type FormattedDiffSection = {
  rows: Record<string, unknown>[];
  count: number;
  value_multiplier?: number;
  type_label?: string;
};

type FormattedDiff = {
  new_positions?: FormattedDiffSection;
  closed_positions?: FormattedDiffSection;
  share_changes?: FormattedDiffSection;
  has_any?: boolean;
};

type ComparePayload = {
  fund: string;
  old_accession: string;
  new_accession: string;
  counts: { new: number; closed: number; increased: number; decreased: number };
  highlights?: CompareHighlight[];
  top_movers?: TopMovers;
  formatted_diff?: FormattedDiff;
};

const SNAPSHOT_COLUMN_ORDER = [
  "Ticker",
  "Type",
  "Issuer",
  "CUSIP",
  "Class",
  "Shares",
  "Put/Call",
  "Value",
];

const HISTORY_COLUMN_ORDER = [
  "Filing Date",
  "Accession",
  "Normalized Positions",
  "Raw 13F Lines",
  "Portfolio Value",
];

const NEW_POSITIONS_COLUMN_ORDER = [
  "Issuer",
  "CUSIP",
  "Class",
  "Put/Call",
  "Shares",
  "Value",
  "Type",
];

const CLOSED_POSITIONS_COLUMN_ORDER = [
  "Issuer",
  "CUSIP",
  "Class",
  "Put/Call",
  "Previous Shares",
  "Previous Value",
  "Type",
];

const CHANGES_COLUMN_ORDER = [
  "Issuer",
  "Direction",
  "Delta %",
  "Delta Shares",
  "Delta Value %",
  "Delta Value",
  "Shares Before",
  "Shares After",
  "Value Before",
  "Value After",
  "CUSIP",
  "Class",
  "Put/Call",
  "Type",
];

const TOP_MOVERS_COLUMN_ORDER = [
  "Ticker",
  "Type",
  "Movement",
  "Issuer",
  "Delta Shares",
  "Delta %",
  "Delta Value",
  "Shares Before",
  "Shares After",
  "CUSIP",
  "Class",
  "Put/Call",
];

const POSITION_INSIGHT_DETAIL_ORDER = [
  "Ticker",
  "Type",
  "Assumed Transaction Date",
  "Filing Date",
  "Issuer",
  "CUSIP",
  "Class",
  "Shares",
  "Put/Call",
  "Value",
  "Implied Filing Price",
  "Estimated Contracts",
];

type ComparePreset = "latest" | "manual";

function buildSnapshotExportHref(fund: string, accession: string, view: string, topN: number, filter: string) {
  const params = new URLSearchParams({
    view,
    top_n: String(topN),
  });
  if (filter) params.set("filter", filter);
  return `/api/funds/${encodeURIComponent(fund)}/accessions/${encodeURIComponent(accession)}/holdings/export?${params.toString()}`;
}

function buildHistoryExportHref(fund: string) {
  return `/api/funds/${encodeURIComponent(fund)}/history/export`;
}

function buildSankeyHref(
  fund: string,
  oldAcc: string,
  newAcc: string,
  topN: number,
  topNBuys: number,
  topNSells: number,
  includeOptions: boolean,
) {
  const params = new URLSearchParams({
    top_n: String(topN),
    top_n_buys: String(topNBuys),
    top_n_sells: String(topNSells),
    scale_mode: "linear",
    min_visible_pct: "0",
    include_options: String(includeOptions),
  });
  return `/api/funds/${encodeURIComponent(fund)}/compare/charts/sankey?old_accession=${encodeURIComponent(
    oldAcc,
  )}&new_accession=${encodeURIComponent(newAcc)}&${params.toString()}`;
}

function buildLanesHref(
  fund: string,
  oldAcc: string,
  newAcc: string,
  topN: number,
  topNBuys: number,
  topNSells: number,
  includeOptions: boolean,
) {
  const params = new URLSearchParams({
    top_n: String(topN),
    top_n_buys: String(topNBuys),
    top_n_sells: String(topNSells),
    include_options: String(includeOptions),
  });
  return `/api/funds/${encodeURIComponent(fund)}/compare/charts/lanes?old_accession=${encodeURIComponent(
    oldAcc,
  )}&new_accession=${encodeURIComponent(newAcc)}&${params.toString()}`;
}

function buildSectionExportHref(
  fund: string,
  section: string,
  oldAcc: string,
  newAcc: string,
) {
  return `/api/funds/${encodeURIComponent(fund)}/compare/export/${section}?old_accession=${encodeURIComponent(
    oldAcc,
  )}&new_accession=${encodeURIComponent(newAcc)}`;
}

function safeFileToken(value: string): string {
  const token = value.trim().replace(/[^0-9A-Za-z._-]+/g, "_").replace(/^_+|_+$/g, "");
  return token || "export";
}

function fmtSignedQuantity(value: unknown): string {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  const sign = num > 0 ? "+" : num < 0 ? "" : "";
  return Number.isInteger(num) ? `${sign}${num.toLocaleString()}` : `${sign}${num.toFixed(2)}`;
}

function fmtValueDollars(value: unknown): string {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  if (num === 0) return "-";
  if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
  if (num >= 1e6) return `$${(num / 1e6).toFixed(1)}M`;
  if (num >= 1e3) return `$${(num / 1e3).toFixed(0)}k`;
  return `$${num.toLocaleString()}`;
}

function fmtSignedValueDollars(value: unknown): string {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  if (num === 0) return "$0";
  const sign = num > 0 ? "+" : "-";
  const abs = fmtValueDollars(Math.abs(num));
  return `${sign}${abs}`;
}

function fmtPct(value: unknown): string {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${num.toFixed(1)}%`;
}

function fmtSignedPct(value: unknown): string {
  if (value === null || value === undefined) return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${num >= 0 ? "+" : ""}${num.toFixed(1)}%`;
}

const DEFAULT_FUND_CANDIDATES = ["Situational Awareness LP (Leopold Aschenbrenner)"];

function getDefaultFund(funds: string[]): string {
  for (const candidate of DEFAULT_FUND_CANDIDATES) {
    if (funds.includes(candidate)) return candidate;
  }
  return funds[0] ?? "";
}

type TransitionDrilldownProps = {
  formattedDiff: FormattedDiff | undefined;
  loading: boolean;
  caption?: string;
};

function TransitionDrilldownTables({ formattedDiff, loading, caption }: TransitionDrilldownProps) {
  const newSection = formattedDiff?.new_positions;
  const closedSection = formattedDiff?.closed_positions;
  const changesSection = formattedDiff?.share_changes;
  const hasNew = Boolean(newSection?.count);
  const hasClosed = Boolean(closedSection?.count);
  const hasChanges = Boolean(changesSection?.count);

  const defaultTab = hasNew ? "new" : hasClosed ? "closed" : hasChanges ? "changes" : null;

  return (
    <div>
      {caption ? (
        <Text size="sm" c="dimmed" mb="sm">
          {caption}
        </Text>
      ) : null}
      {!hasNew && !hasClosed && !hasChanges ? (
        <Alert variant="light" color="green" radius="md">
          No position-level changes for this transition.
        </Alert>
      ) : (
        <Tabs defaultValue={defaultTab ?? undefined} variant="pills">
          <Tabs.List>
            <Tabs.Tab value="new" disabled={!hasNew}>
              New ({newSection?.count ?? 0})
            </Tabs.Tab>
            <Tabs.Tab value="closed" disabled={!hasClosed}>
              Closed ({closedSection?.count ?? 0})
            </Tabs.Tab>
            <Tabs.Tab value="changes" disabled={!hasChanges}>
              Share changes ({changesSection?.count ?? 0})
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="new" pt="md">
            {hasNew && newSection ? (
              <DataTable
                columns={newSection.rows[0] ? Object.keys(newSection.rows[0]) : []}
                rows={newSection.rows}
                columnOrder={NEW_POSITIONS_COLUMN_ORDER}
                cellLinks={ISSUER_CELL_LINK}
                maxHeight={360}
                stickyHeader
                loading={loading}
                loadingColumns={NEW_POSITIONS_COLUMN_ORDER.length}
              />
            ) : null}
          </Tabs.Panel>

          <Tabs.Panel value="closed" pt="md">
            {hasClosed && closedSection ? (
              <DataTable
                columns={closedSection.rows[0] ? Object.keys(closedSection.rows[0]) : []}
                rows={closedSection.rows}
                columnOrder={CLOSED_POSITIONS_COLUMN_ORDER}
                cellLinks={ISSUER_CELL_LINK}
                maxHeight={360}
                stickyHeader
                loading={loading}
                loadingColumns={CLOSED_POSITIONS_COLUMN_ORDER.length}
              />
            ) : null}
          </Tabs.Panel>

          <Tabs.Panel value="changes" pt="md">
            {hasChanges && changesSection ? (
              <DataTable
                columns={changesSection.rows[0] ? Object.keys(changesSection.rows[0]) : []}
                rows={changesSection.rows}
                columnOrder={CHANGES_COLUMN_ORDER}
                cellLinks={ISSUER_CELL_LINK}
                maxHeight={360}
                stickyHeader
                loading={loading}
                loadingColumns={CHANGES_COLUMN_ORDER.length}
              />
            ) : null}
          </Tabs.Panel>
        </Tabs>
      )}
    </div>
  );
}

export function FundAnalysisPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialFund = searchParams.get("fund") ?? "";
  const initialTab = (searchParams.get("tab") as "snapshot" | "timeline" | "compare" | null) ?? "snapshot";
  const initialOldAcc = searchParams.get("old") ?? "";
  const initialNewAcc = searchParams.get("new") ?? "";

  const [fund, setFund] = useState(initialFund);
  const [tab, setTab] = useState<"snapshot" | "timeline" | "compare">(initialTab);

  // Snapshot tab state
  const [accession, setAccession] = useState("");
  const [view, setView] = useState<"normalized" | "raw">("normalized");
  const [topN, setTopN] = useState(10);
  const [filter, setFilter] = useState("");

  // Compare tab state
  const [comparePreset, setComparePreset] = useState<ComparePreset>("latest");
  const [oldAccession, setOldAccession] = useState(initialOldAcc);
  const [newAccession, setNewAccession] = useState(initialNewAcc);
  const [sankeyTopN, setSankeyTopN] = useState(20);
  const [sankeyTopNBuys, setSankeyTopNBuys] = useState(20);
  const [sankeyTopNSells, setSankeyTopNSells] = useState(20);
  const [sankeyIncludeOptions, setSankeyIncludeOptions] = useState(false);
  const [transitionIndex, setTransitionIndex] = useState(0);

  // Insight key (resets when accession changes)
  const [insightKey, setInsightKey] = useState("");

  const fundsQuery = useQuery({
    queryKey: ["funds"],
    queryFn: () => apiGet<{ funds: string[] }>("/api/funds"),
  });

  const headerQuery = useQuery({
    queryKey: ["fund-header", fund],
    queryFn: () => apiGet<FundHeader>(`/api/funds/${encodeURIComponent(fund)}`),
    enabled: Boolean(fund),
  });

  const accessions = headerQuery.data?.accessions ?? [];

  useEffect(() => {
    if (!accession && accessions.length > 0) {
      setAccession(accessions[0].accession_number);
    }
    if (accession && !accessions.some((entry) => entry.accession_number === accession)) {
      setAccession(accessions[0]?.accession_number ?? "");
    }
  }, [accessions, accession]);

  useEffect(() => {
    if (comparePreset !== "latest") return;
    if (accessions.length === 0) return;
    const [latest, prev] = accessions;
    if (!latest) return;
    setNewAccession(latest.accession_number);
    setOldAccession(prev?.accession_number ?? latest.accession_number);
  }, [accessions, comparePreset]);

  useEffect(() => {
    setInsightKey("");
  }, [accession]);

  const snapshotQuery = useQuery({
    queryKey: ["fund-snapshot", fund, accession, view, topN, filter],
    queryFn: () =>
      apiGet<SnapshotPayload>(
        `/api/funds/${encodeURIComponent(fund)}/accessions/${encodeURIComponent(accession)}/holdings?view=${view}&top_n=${topN}&filter=${encodeURIComponent(
          filter,
        )}`,
      ),
    enabled: Boolean(fund && accession),
  });

  const historyQuery = useQuery({
    queryKey: ["fund-history", fund],
    queryFn: () =>
      apiGet<HistoryPayload>(`/api/funds/${encodeURIComponent(fund)}/history`),
    enabled: Boolean(fund),
  });

  const compareEnabled =
    Boolean(fund) && Boolean(newAccession) && Boolean(oldAccession) && oldAccession !== newAccession;

  const compareQuery = useQuery({
    queryKey: ["fund-compare", fund, oldAccession, newAccession],
    queryFn: () =>
      apiGet<ComparePayload>(
        `/api/funds/${encodeURIComponent(fund)}/compare?old_accession=${encodeURIComponent(
          oldAccession,
        )}&new_accession=${encodeURIComponent(newAccession)}`,
      ),
    enabled: compareEnabled,
  });

  const sankeyQuery = useQuery({
    queryKey: [
      "fund-sankey",
      fund,
      oldAccession,
      newAccession,
      sankeyTopN,
      sankeyTopNBuys,
      sankeyTopNSells,
      sankeyIncludeOptions,
    ],
    queryFn: () =>
      apiGet<{
        node?: { label: string[]; color?: string[] };
        link?: { source: number[]; target: number[]; value: number[]; color?: string[] };
        movements?: Record<string, unknown>[];
        value_multiplier?: number;
        scale_mode?: string;
        min_visible_pct?: number;
        include_options?: boolean;
      }>(
        buildSankeyHref(
          fund,
          oldAccession,
          newAccession,
          sankeyTopN,
          sankeyTopNBuys,
          sankeyTopNSells,
          sankeyIncludeOptions,
        ),
      ),
    enabled: compareEnabled,
  });

  const lanesQuery = useQuery({
    queryKey: [
      "fund-lanes",
      fund,
      oldAccession,
      newAccession,
      sankeyTopN,
      sankeyTopNBuys,
      sankeyTopNSells,
      sankeyIncludeOptions,
    ],
    queryFn: () =>
      apiGet<{ rows: Record<string, unknown>[] }>(
        buildLanesHref(
          fund,
          oldAccession,
          newAccession,
          sankeyTopN,
          sankeyTopNBuys,
          sankeyTopNSells,
          sankeyIncludeOptions,
        ),
      ),
    enabled: compareEnabled,
  });

  const snapshot = snapshotQuery.data;
  const history = historyQuery.data;
  const compare = compareQuery.data;

  const snapshotRows = snapshot?.rows ?? [];
  const snapshotColumns = snapshotRows[0] ? Object.keys(snapshotRows[0]) : [];

  const positionsChart = history?.charts?.positions;
  const valueChart = history?.charts?.value;

  const transitions = history?.transitions ?? [];
  const latestFirstTransitions = useMemo(() => [...transitions].reverse(), [transitions]);
  const transitionsChart = history?.transitions_chart ?? null;
  const selectedTransition =
    latestFirstTransitions.length > 0
      ? latestFirstTransitions[Math.min(transitionIndex, latestFirstTransitions.length - 1)]
      : undefined;

  const insightOptions = snapshot?.position_insight?.options ?? [];
  const insightLabels = snapshot?.position_insight?.labels ?? {};
  const effectiveInsightKey = insightKey || snapshot?.position_insight?.selected_key || "";
  const insightDetail = useMemo(() => {
    if (!snapshot?.position_insight?.detail) return null;
    if (effectiveInsightKey && effectiveInsightKey !== snapshot.position_insight.selected_key) {
      return null;
    }
    return snapshot.position_insight.detail;
  }, [snapshot?.position_insight, effectiveInsightKey]);

  const headerKpis = useMemo(() => {
    const items: { label: string; value: string }[] = [];
    items.push({ label: "Latest filing", value: formatDateValue(headerQuery.data?.latest_filing) });
    items.push({
      label: "Quarters",
      value: (headerQuery.data?.quarters ?? 0).toLocaleString(),
    });
    items.push({
      label: "Current positions",
      value: (headerQuery.data?.current_positions ?? 0).toLocaleString(),
    });
    return items;
  }, [headerQuery.data]);

  const transitionDrillHref = selectedTransition
    ? `/fund-analysis?fund=${encodeURIComponent(fund)}&tab=compare&old=${encodeURIComponent(
        selectedTransition.from_accession_number,
      )}&new=${encodeURIComponent(selectedTransition.to_accession_number)}`
    : "";

  const onSelectTransition = (index: number) => {
    const transition = latestFirstTransitions[index];
    if (!transition) return;
    setTransitionIndex(index);
    setOldAccession(transition.from_accession_number);
    setNewAccession(transition.to_accession_number);
    setComparePreset("manual");
  };

  const goToHoldingsSearch = useMemo(
    () => (label: string) => {
      // Position labels from lanes/sankey charts carry class/put-call suffixes
      // (e.g. "Alphabet Inc. (Class C CALL)"). The holdings search ANDs whitespace
      // separated terms, so trailing suffix tokens like "(Class" would yield zero
      // matches. Strip the first parenthetical to recover the bare issuer name.
      const withoutParens = label.replace(/\s*\([^)]*\)\s*$/, "").trim();
      const text = withoutParens || label.trim();
      if (!text || text.toLowerCase() === "unknown") return;
      navigate(`/holdings-search?q=${encodeURIComponent(text)}`);
    },
    [navigate],
  );

  const onTransitionChartClick = (label: string) => {
    const text = label.trim();
    if (!text) return;
    const matchIdx = latestFirstTransitions.findIndex(
      (transition) => `${transition.from_filing_date} → ${transition.to_filing_date}` === text,
    );
    if (matchIdx >= 0) onSelectTransition(matchIdx);
  };

  const updateTab = (next: "snapshot" | "timeline" | "compare") => {
    setTab(next);
    const params: Record<string, string> = {};
    if (fund) params.fund = fund;
    params.tab = next;
    if (next === "compare") {
      if (oldAccession) params.old = oldAccession;
      if (newAccession) params.new = newAccession;
    }
    setSearchParams(params);
  };

  const updateFund = (next: string) => {
    setFund(next);
    setAccession("");
    setInsightKey("");
    const params: Record<string, string> = {};
    if (next) params.fund = next;
    params.tab = tab;
    setSearchParams(params);
  };

  useEffect(() => {
    if (searchParams.get("fund")) return;
    const funds = fundsQuery.data?.funds;
    if (!funds?.length) return;
    updateFund(getDefaultFund(funds));
  }, [fundsQuery.data?.funds, searchParams]);

  return (
    <div>
      <Paper withBorder p="md" radius="md" bg="white" mb="lg">
        <Group justify="space-between" align="flex-end" wrap="wrap" gap="md">
          <Select
            label="Fund"
            searchable
            data={fundsQuery.data?.funds ?? []}
            value={fund || null}
            onChange={(value) => updateFund(value ?? "")}
            placeholder="Select a fund"
            style={{ minWidth: 280 }}
          />
          {fund ? (
            headerQuery.isLoading ? (
              <KpiLoading count={3} />
            ) : (
              <KpiGrid items={headerKpis} />
            )
          ) : null}
        </Group>
        {fund ? (
          <Text size="sm" c="dimmed" mt="sm">
            One fund workspace for filing inventory, quarter history, and position-level change analysis.
          </Text>
        ) : null}
      </Paper>

      {headerQuery.data && headerQuery.data.has_db_holdings === false ? (
        <AlertBanner variant="warning" title="Fund has no DB holdings yet">
          This fund is selectable from configuration, but the holdings DB does not contain rows for this fund
          yet. Some views may use local cache metadata when available.
        </AlertBanner>
      ) : null}

      {!fund ? (
        fundsQuery.isLoading ? (
          <Text c="dimmed">Loading fund list…</Text>
        ) : (
          <Text>Select a fund to begin.</Text>
        )
      ) : null}

      {fund ? (
        <Tabs
          value={tab}
          onChange={(value) => value && updateTab(value as typeof tab)}
          variant="pills"
          color="blue"
          classNames={{
            list: "f8-sticky-tab-bar",
            tab: "f8-sticky-tab",
          }}
        >
          <div className="f8-sticky-fund-row">
            <Text className="f8-sticky-fund-name" fw={700} title={fund || undefined}>
              {fund || "Select a fund"}
            </Text>
            <Tabs.List grow>
              <Tabs.Tab value="snapshot">Snapshot</Tabs.Tab>
              <Tabs.Tab value="timeline">Timeline</Tabs.Tab>
              <Tabs.Tab value="compare">Compare</Tabs.Tab>
            </Tabs.List>
          </div>

          <Tabs.Panel value="snapshot">
            <Paper withBorder p="md" radius="md" bg="white" mb="lg">
              <SimpleGrid cols={{ base: 1, md: 3 }} mb="md">
                <Select
                  label="Quarter (accession)"
                  data={accessions.map((entry) => ({
                    value: entry.accession_number,
                    label: formatAccessionLabel(entry.label),
                  }))}
                  value={accession || null}
                  onChange={(value) => setAccession(value ?? "")}
                />
                <Select
                  label="Holdings view"
                  data={[
                    { value: "normalized", label: "Normalized by CUSIP" },
                    { value: "raw", label: "Raw 13F lines" },
                  ]}
                  value={view}
                  onChange={(value) => setView((value as "normalized" | "raw") ?? "normalized")}
                />
                <div>
                  <Text size="sm" fw={500} mb={8}>
                    Top holdings
                  </Text>
                  <Slider value={topN} onChange={setTopN} min={5} max={25} step={5} />
                </div>
              </SimpleGrid>
              <TextInput
                label="Filter by ticker, name, or CUSIP"
                value={filter}
                onChange={(event) => setFilter(event.currentTarget.value)}
                mb="md"
              />

              {snapshot?.value_multiplier ? (
                <Text size="sm" c="dimmed" mb="sm">
                  Value scale for this filing is auto-normalized using implied per-share prices
                  (multiplier x{snapshot.value_multiplier}). Normalized aggregates rows with the same CUSIP
                  and is best for portfolio analysis.
                </Text>
              ) : null}

              {snapshot?.metrics ? (
                <KpiGrid
                  items={[
                    {
                      label: "Raw 13F lines",
                      value: Number(snapshot.metrics.raw_lines ?? 0).toLocaleString(),
                    },
                    {
                      label: "Normalized positions",
                      value: Number(snapshot.metrics.normalized_positions ?? 0).toLocaleString(),
                    },
                    {
                      label: "Compression",
                      value: `${(((snapshot.metrics.compression ?? 0) as number) * 100).toFixed(1)}%`,
                    },
                  ]}
                />
              ) : snapshotQuery.isLoading ? (
                <KpiLoading count={3} />
              ) : null}

              <BarChart
                chart={snapshot?.chart}
                loading={snapshotQuery.isLoading && !snapshot?.chart?.x?.length}
                onPointClick={goToHoldingsSearch}
              />
              <DataTable
                columns={snapshotColumns}
                rows={snapshotRows}
                columnOrder={SNAPSHOT_COLUMN_ORDER}
                cellLinks={HOLDINGS_SEARCH_CELL_LINKS}
                maxHeight={420}
                stickyHeader
                loading={snapshotQuery.isLoading}
              />

              <Group justify="flex-end" mt="md">
                <ExportLink
                  href={
                    accession
                      ? buildSnapshotExportHref(fund, accession, view, topN, filter)
                      : ""
                  }
                  label="Download holdings CSV"
                  fileName={`f8_13f_${safeFileToken(fund)}_${accession}_${view}.csv`}
                />
              </Group>
            </Paper>

            {snapshot && !snapshot.empty ? (
              <Paper withBorder p="md" radius="md" bg="white" mb="lg">
                <SectionHeader
                  title="Position insight"
                  caption="Drill into a single normalized position to inspect per-row values, option structure, and implied filing price."
                />
                <Select
                  label="Position"
                  data={insightOptions.map((key) => ({ value: key, label: insightLabels[key] ?? key }))}
                  value={effectiveInsightKey || null}
                  onChange={(value) => setInsightKey(value ?? "")}
                  placeholder="No positions to inspect"
                  mb="md"
                />
                {insightDetail?.metrics ? (
                  <KpiGrid
                    items={[
                      { label: "Assumed transaction date", value: insightDetail.metrics.transaction_date ?? "-" },
                      { label: "Implied filing price", value: insightDetail.metrics.implied_filing_price ?? "-" },
                      { label: "Reported value", value: insightDetail.metrics.reported_value ?? "-" },
                      { label: "Underlying shares", value: insightDetail.metrics.underlying_shares ?? "-" },
                    ]}
                  />
                ) : null}
                {insightDetail?.captions?.map((caption, index) => (
                  <Text key={`insight-caption-${index}`} size="sm" c="dimmed" mb={6}>
                    {caption}
                  </Text>
                ))}

                <DataTable
                  columns={
                    insightDetail?.rows && insightDetail.rows[0]
                      ? Object.keys(insightDetail.rows[0])
                      : []
                  }
                  rows={insightDetail?.rows ?? []}
                  columnOrder={POSITION_INSIGHT_DETAIL_ORDER}
                  cellLinks={HOLDINGS_SEARCH_CELL_LINKS}
                  maxHeight={360}
                  stickyHeader
                  loading={snapshotQuery.isLoading}
                  loadingColumns={POSITION_INSIGHT_DETAIL_ORDER.length}
                  emptyMessage="No rows match the current filter."
                />
              </Paper>
            ) : null}
          </Tabs.Panel>

          <Tabs.Panel value="timeline">
            <Paper withBorder p="md" radius="md" bg="white" mb="lg">
              <Group justify="space-between" align="flex-start" mb="md">
                <div>
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                    Quarter timeline
                  </Text>
                  <Text size="sm" c="dimmed">
                    Quarter-over-quarter history with portfolio trajectory and QoQ activity counts.
                  </Text>
                </div>
                <ExportLink
                  href={buildHistoryExportHref(fund)}
                  label="Download fund timeline CSV"
                  fileName={`f8_13f_${safeFileToken(fund)}_history.csv`}
                />
              </Group>

              {history?.summary ? (
                <KpiGrid
                  items={[
                    {
                      label: "Available quarters",
                      value: Number(history.summary.quarters ?? 0).toLocaleString(),
                    },
                    {
                      label: "Latest filing",
                      value: formatDateValue(history.summary.latest_filing),
                    },
                    {
                      label: "Current positions",
                      value: Number(history.summary.current_positions ?? 0).toLocaleString(),
                      delta:
                        history.summary.positions_delta !== undefined
                          ? fmtSignedQuantity(history.summary.positions_delta)
                          : null,
                    },
                    {
                      label: "Latest filing value",
                      value: fmtValueDollars(history.summary.latest_value),
                      delta:
                        history.summary.value_delta !== undefined && history.summary.value_delta !== null
                          ? fmtSignedValueDollars(history.summary.value_delta)
                          : null,
                    },
                  ]}
                />
              ) : historyQuery.isLoading ? (
                <KpiLoading count={4} />
              ) : null}

              {history?.summary?.value_multiplier_summary ? (
                <Text size="sm" c="dimmed" mb="sm">
                  Historical portfolio values are normalized by filing (multipliers:{" "}
                  {history.summary.value_multiplier_summary}).
                </Text>
              ) : null}

              <DataTable
                columns={
                  history?.history && history.history[0] ? Object.keys(history.history[0]) : []
                }
                rows={history?.history ?? []}
                columnOrder={HISTORY_COLUMN_ORDER}
                maxHeight={300}
                stickyHeader
                loading={historyQuery.isLoading}
                loadingColumns={HISTORY_COLUMN_ORDER.length}
              />

              <SimpleGrid cols={{ base: 1, md: 2 }} mt="md">
                <LineChart
                  chart={positionsChart ?? undefined}
                  loading={historyQuery.isLoading && !positionsChart?.x?.length}
                />
                {valueChart ? (
                  <LineChart chart={valueChart} />
                ) : historyQuery.isLoading ? (
                  <ChartLoading label="Loading portfolio value chart…" />
                ) : (
                  <Alert variant="light" color="yellow" radius="md" mt="md">
                    Portfolio values are not available for this fund in the current DB.
                  </Alert>
                )}
              </SimpleGrid>
            </Paper>

            {latestFirstTransitions.length > 0 ? (
              <Paper withBorder p="md" radius="md" bg="white" mb="lg">
                <SectionHeader
                  title="Quarter-over-quarter activity"
                  caption="Bars show per-transition counts of new / closed / increased / decreased positions. Click a bar cluster to drill into that transition below."
                />
                <GroupedBarChart
                  chart={transitionsChart}
                  loading={historyQuery.isLoading && !transitionsChart?.x?.length}
                  onPointClick={onTransitionChartClick}
                />

                <SimpleGrid cols={{ base: 1, md: 2 }} mt="md">
                  <Select
                    label="Transition drill-down"
                    data={latestFirstTransitions.map((transition, index) => ({
                      value: String(index),
                      label: `${formatDateValue(transition.from_filing_date)} → ${formatDateValue(
                        transition.to_filing_date,
                      )} | ${transition.from_accession_number} → ${transition.to_accession_number}`,
                    }))}
                    value={String(Math.min(transitionIndex, latestFirstTransitions.length - 1))}
                    onChange={(value) => onSelectTransition(Number(value ?? 0))}
                  />
                  <div />
                </SimpleGrid>

                {selectedTransition ? (
                  <>
                    <KpiGrid
                      items={[
                        { label: "New positions", value: selectedTransition.new_count.toLocaleString() },
                        { label: "Closed positions", value: selectedTransition.closed_count.toLocaleString() },
                        { label: "Increased", value: selectedTransition.increased_count.toLocaleString() },
                        { label: "Decreased", value: selectedTransition.decreased_count.toLocaleString() },
                      ]}
                    />
                    <Group justify="space-between" mt="md">
                      <Button
                        component="a"
                        href={transitionDrillHref}
                        onClick={(event) => {
                          event.preventDefault();
                          if (transitionDrillHref) {
                            window.history.pushState(null, "", transitionDrillHref);
                            updateTab("compare");
                          }
                        }}
                        variant="light"
                      >
                        Inspect in Compare
                      </Button>
                    </Group>
                    <Text size="sm" c="dimmed" mt="xs">
                      Detailed new, closed, and share-change tables are consolidated in Compare so each
                      transition is inspected in one place.
                    </Text>

                    <Paper withBorder p="md" radius="md" bg="white" mt="md">
                      <SectionHeader
                        title="Position drill-down"
                        caption={`New, closed, increased, and decreased positions for ${formatDateValue(
                          selectedTransition.from_filing_date,
                        )} → ${formatDateValue(selectedTransition.to_filing_date)}.`}
                      />
                      {compareQuery.isLoading && !compare?.formatted_diff ? (
                        <ChartLoading label="Loading transition details…" />
                      ) : compare?.formatted_diff ? (
                        <TransitionDrilldownTables
                          formattedDiff={compare.formatted_diff}
                          loading={compareQuery.isLoading}
                        />
                      ) : (
                        <Text size="sm" c="dimmed">
                          No detailed rows available for this transition.
                        </Text>
                      )}
                    </Paper>
                  </>
                ) : null}
              </Paper>
            ) : null}
          </Tabs.Panel>

          <Tabs.Panel value="compare">
            {accessions.length < 2 ? (
              <AlertBanner variant="warning" title="Not enough quarters to compare">
                At least 2 quarters are required to compute the diff for this fund.
              </AlertBanner>
            ) : (
              <Paper withBorder p="md" radius="md" bg="white" mb="lg">
                <Group justify="space-between" align="flex-end" wrap="wrap" gap="md" mb="md">
                  <Radio.Group
                    label="Comparison preset"
                    value={comparePreset}
                    onChange={(value) => setComparePreset(value as ComparePreset)}
                  >
                    <Group mt="xs">
                      <Radio value="latest" label="Latest vs previous" />
                      <Radio value="manual" label="Manual quarters" />
                    </Group>
                  </Radio.Group>
                  <Group gap="md">
                    {comparePreset === "manual" ? (
                      <>
                        <Select
                          label="NEW quarter"
                          data={accessions.map((entry) => ({
                            value: entry.accession_number,
                            label: formatAccessionLabel(entry.label),
                          }))}
                          value={newAccession || null}
                          onChange={(value) => setNewAccession(value ?? "")}
                          searchable
                        />
                        <Select
                          label="PREVIOUS quarter"
                          data={accessions.map((entry) => ({
                            value: entry.accession_number,
                            label: formatAccessionLabel(entry.label),
                          }))}
                          value={oldAccession || null}
                          onChange={(value) => setOldAccession(value ?? "")}
                          searchable
                        />
                      </>
                    ) : (
                      <>
                        <TextInput
                          label="NEW quarter"
                          value={
                            newAccession
                              ? formatAccessionLabel(
                                  accessions.find((entry) => entry.accession_number === newAccession)?.label ?? "",
                                )
                              : ""
                          }
                          disabled
                        />
                        <TextInput
                          label="PREVIOUS quarter"
                          value={
                            oldAccession
                              ? formatAccessionLabel(
                                  accessions.find((entry) => entry.accession_number === oldAccession)?.label ?? "",
                                )
                              : ""
                          }
                          disabled
                        />
                      </>
                    )}
                  </Group>
                </Group>

                {oldAccession === newAccession && oldAccession ? (
                  <AlertBanner variant="warning" title="Pick two different quarters">
                    Select two different quarters to compute a comparison.
                  </AlertBanner>
                ) : null}

                <Text size="sm" c="dimmed" mb="md">
                  Compare is the position-level change workspace. Common shares, CALLs, and PUTs remain
                  separate even when they share the same underlying CUSIP; positions without CUSIP use the
                  fallback issuer/class/put-call key.
                </Text>

                {compare?.counts ? (
                  <KpiGrid
                    items={[
                      { label: "New positions", value: compare.counts.new.toLocaleString() },
                      { label: "Closed positions", value: compare.counts.closed.toLocaleString() },
                      { label: "Increased", value: compare.counts.increased.toLocaleString() },
                      { label: "Decreased", value: compare.counts.decreased.toLocaleString() },
                    ]}
                  />
                ) : compareQuery.isLoading ? (
                  <KpiLoading count={4} />
                ) : null}

                {compare?.highlights ? (
                  <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md" mt="md">
                    {compare.highlights.map((highlight) => (
                      <Paper key={highlight.label} withBorder p="md" radius="md" bg="white">
                        <Text size="xs" tt="uppercase" fw={700} c="dimmed">
                          {highlight.label}
                        </Text>
                        <Text size="xl" fw={700} mt={4}>
                          {highlight.value}
                        </Text>
                        <Badge variant="light" color="gray" mt={6}>
                          {highlight.context}
                        </Badge>
                        <Text size="sm" c="dimmed" mt={6}>
                          {highlight.position_label}
                        </Text>
                      </Paper>
                    ))}
                  </SimpleGrid>
                ) : null}

                {compare?.formatted_diff?.new_positions?.count ||
                compare?.formatted_diff?.closed_positions?.count ||
                compare?.formatted_diff?.share_changes?.count ? (
                  <Paper withBorder p="md" radius="md" bg="white" mt="lg">
                    <SectionHeader
                      title="Top movers"
                      caption={`Largest position changes by absolute share delta across new, closed, increased, and decreased positions (value multiplier x${
                        compare?.top_movers?.value_multiplier ?? 1
                      }).`}
                      right={
                        <ExportLink
                          href={buildSectionExportHref(fund, "top_movers", oldAccession, newAccession)}
                          label="Download top movers CSV"
                          fileName={`f8_13f_${safeFileToken(fund)}_top_movers.csv`}
                        />
                      }
                    />
                    <DataTable
                      columns={
                        compare?.top_movers?.rows && compare.top_movers.rows[0]
                          ? Object.keys(compare.top_movers.rows[0])
                          : []
                      }
                      rows={compare?.top_movers?.rows ?? []}
                      columnOrder={TOP_MOVERS_COLUMN_ORDER}
                      cellLinks={HOLDINGS_SEARCH_CELL_LINKS}
                      maxHeight={420}
                      stickyHeader
                      loading={compareQuery.isLoading}
                      loadingColumns={TOP_MOVERS_COLUMN_ORDER.length}
                    />
                  </Paper>
                ) : null}

                <Paper withBorder p="md" radius="md" bg="white" mt="lg">
                  <SectionHeader
                    title="Visual movement summary"
                    caption="Delta Shares = NEW quarter shares - PREVIOUS quarter shares. Ribbon width is proportional to share quantity (linear scale). PUT/CALL options are excluded by default."
                  />
                  <SimpleGrid cols={{ base: 1, md: 2, lg: 4 }} mb="md">
                    <NumberInput
                      label="Top N buy flows"
                      value={sankeyTopNBuys}
                      min={5}
                      max={50}
                      step={5}
                      onChange={(value) =>
                        setSankeyTopNBuys(typeof value === "number" ? value : Number(value) || 20)
                      }
                    />
                    <NumberInput
                      label="Top N sell flows"
                      value={sankeyTopNSells}
                      min={5}
                      max={50}
                      step={5}
                      onChange={(value) =>
                        setSankeyTopNSells(typeof value === "number" ? value : Number(value) || 20)
                      }
                    />
                    <div>
                      <Text size="sm" fw={500} mb={8}>
                        Position nodes shown
                      </Text>
                      <Slider
                        value={sankeyTopN}
                        onChange={setSankeyTopN}
                        min={5}
                        max={40}
                        step={5}
                        marks={[
                          { value: 5, label: "5" },
                          { value: 20, label: "20" },
                          { value: 40, label: "40" },
                        ]}
                      />
                    </div>
                    <div>
                      <Text size="sm" fw={500} mb={8}>
                        Options filter
                      </Text>
                      <Switch
                        label="Include PUT/CALL options"
                        checked={sankeyIncludeOptions}
                        onChange={(event) => setSankeyIncludeOptions(event.currentTarget.checked)}
                      />
                    </div>
                  </SimpleGrid>
                  {sankeyQuery.data ? (
                    <Text size="sm" c="dimmed" mb="sm">
                      Ribbon width is proportional to share delta (linear scale).
                      {" "}PUT/CALL options are{" "}
                      {sankeyQuery.data.include_options ? "included" : "excluded"}. Hover labels
                      show raw share deltas and auto-normalized delta values (value multiplier x
                      {sankeyQuery.data.value_multiplier ?? 1}).
                    </Text>
                  ) : null}
                  <SankeyChart
                    data={sankeyQuery.data}
                    loading={sankeyQuery.isLoading}
                    onPointClick={goToHoldingsSearch}
                  />

                  <LanesChart
                    chart={
                      lanesQuery.data?.rows?.length
                        ? {
                            title: `Previous to new shares by position - ${fund}`,
                            rows: lanesQuery.data.rows,
                          }
                        : null
                    }
                    loading={lanesQuery.isLoading}
                    onPointClick={goToHoldingsSearch}
                  />
                </Paper>

                <Paper withBorder p="md" radius="md" bg="white" mt="lg">
                  <SectionHeader
                    title="Detailed change tables"
                    caption="Formatted positions and share-change rows, sorted by absolute magnitude."
                  />

                  {compare?.formatted_diff?.new_positions?.count ? (
                    <div style={{ marginTop: "0.75rem" }}>
                      <Group justify="space-between" align="flex-end" mb="xs">
                        <div>
                          <Text fw={700}>New positions ({compare.formatted_diff.new_positions.count})</Text>
                          <Text size="sm" c="dimmed">
                            Displayed values are auto-scaled from stored units using implied per-share
                            prices (multiplier x{compare.formatted_diff.new_positions.value_multiplier ?? 1}).
                          </Text>
                        </div>
                        <ExportLink
                          href={buildSectionExportHref(fund, "new_positions", oldAccession, newAccession)}
                          label="Download new positions CSV"
                          fileName={`f8_13f_${safeFileToken(fund)}_new_positions.csv`}
                        />
                      </Group>
                      <DataTable
                        columns={
                          compare.formatted_diff.new_positions.rows[0]
                            ? Object.keys(compare.formatted_diff.new_positions.rows[0])
                            : []
                        }
                        rows={compare.formatted_diff.new_positions.rows}
                        columnOrder={NEW_POSITIONS_COLUMN_ORDER}
                        cellLinks={ISSUER_CELL_LINK}
                        maxHeight={320}
                        stickyHeader
                        loading={compareQuery.isLoading}
                        loadingColumns={NEW_POSITIONS_COLUMN_ORDER.length}
                      />
                    </div>
                  ) : null}

                  {compare?.formatted_diff?.closed_positions?.count ? (
                    <div style={{ marginTop: "1rem" }}>
                      <Group justify="space-between" align="flex-end" mb="xs">
                        <div>
                          <Text fw={700}>Closed positions ({compare.formatted_diff.closed_positions.count})</Text>
                          <Text size="sm" c="dimmed">
                            Displayed values are auto-scaled from stored units using implied per-share
                            prices (multiplier x{compare.formatted_diff.closed_positions.value_multiplier ?? 1}).
                          </Text>
                        </div>
                        <ExportLink
                          href={buildSectionExportHref(fund, "closed_positions", oldAccession, newAccession)}
                          label="Download closed positions CSV"
                          fileName={`f8_13f_${safeFileToken(fund)}_closed_positions.csv`}
                        />
                      </Group>
                      <DataTable
                        columns={
                          compare.formatted_diff.closed_positions.rows[0]
                            ? Object.keys(compare.formatted_diff.closed_positions.rows[0])
                            : []
                        }
                        rows={compare.formatted_diff.closed_positions.rows}
                        columnOrder={CLOSED_POSITIONS_COLUMN_ORDER}
                        cellLinks={ISSUER_CELL_LINK}
                        maxHeight={320}
                        stickyHeader
                        loading={compareQuery.isLoading}
                        loadingColumns={CLOSED_POSITIONS_COLUMN_ORDER.length}
                      />
                    </div>
                  ) : null}

                  {compare?.formatted_diff?.share_changes?.count ? (
                    <div style={{ marginTop: "1rem" }}>
                      <Group justify="space-between" align="flex-end" mb="xs">
                        <div>
                          <Text fw={700}>All share changes ({compare.formatted_diff.share_changes.count})</Text>
                          <Text size="sm" c="dimmed">
                            Sorted by absolute percentage move. Green rows are increases; red rows are
                            decreases. Value columns are auto-scaled from stored units (multiplier x
                            {compare.formatted_diff.share_changes.value_multiplier ?? 1}).
                          </Text>
                        </div>
                        <ExportLink
                          href={buildSectionExportHref(fund, "share_changes", oldAccession, newAccession)}
                          label="Download share changes CSV"
                          fileName={`f8_13f_${safeFileToken(fund)}_share_changes.csv`}
                        />
                      </Group>
                      <DataTable
                        columns={
                          compare.formatted_diff.share_changes.rows[0]
                            ? Object.keys(compare.formatted_diff.share_changes.rows[0])
                            : []
                        }
                        rows={compare.formatted_diff.share_changes.rows}
                        columnOrder={CHANGES_COLUMN_ORDER}
                        cellLinks={ISSUER_CELL_LINK}
                        maxHeight={420}
                        stickyHeader
                        loading={compareQuery.isLoading}
                        loadingColumns={CHANGES_COLUMN_ORDER.length}
                      />
                    </div>
                  ) : null}

                  {!compare?.formatted_diff?.has_any ? (
                    <AlertBanner variant="success" title="No changes between the two quarters">
                      The selected accession pair has no detected position-level changes.
                    </AlertBanner>
                  ) : null}
                </Paper>
              </Paper>
            )}
          </Tabs.Panel>
        </Tabs>
      ) : null}
    </div>
  );
}
