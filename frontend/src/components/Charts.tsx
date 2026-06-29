import Plot, { type PlotParams } from "react-plotly.js";
import type { ReactNode } from "react";
import { Skeleton, Stack, Text } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { formatChartDate } from "@/utils/dateFormat";

type ChartViewport = "compact" | "comfortable" | "wide";

function ChartLoadingPlaceholder({
  height = 360,
  label = "Loading chart…",
}: {
  height?: number;
  label?: string;
}) {
  return (
    <Stack gap="xs" style={{ width: "100%" }}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Skeleton height={height} radius="md" />
    </Stack>
  );
}

function useChartViewport(): ChartViewport {
  const isWide = useMediaQuery("(min-width: 75em)");
  const isCompact = useMediaQuery("(max-width: 48em)");
  if (isWide) return "wide";
  if (isCompact) return "compact";
  return "comfortable";
}

function ChartFrame({
  children,
  minWidth,
}: {
  children: ReactNode;
  minWidth?: number;
}) {
  return (
    <div className="f8-chart-frame" style={minWidth ? { ["--f8-chart-min-width" as string]: `${minWidth}px` } : undefined}>
      {children}
    </div>
  );
}

type ChartSpec = {
  title: string;
  x: Array<string | number>;
  y: Array<string | number>;
  y_label?: string;
};

const TRANSITION_SERIES_COLORS: Record<string, string> = {
  New: "rgba(46, 160, 67, 0.7)",
  Closed: "rgba(248, 81, 73, 0.7)",
  Increased: "rgba(31, 111, 235, 0.7)",
  Decreased: "rgba(255, 161, 0, 0.7)",
};

const DEFAULT_TRANSITION_COLOR = "rgba(139, 148, 158, 0.7)";

function shouldFormatDatesAsLabels(x: Array<string | number>): boolean {
  if (x.length === 0) return false;
  if (typeof x[0] === "number") return false;
  return x.every((value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value));
}

function maybeFormatXTicks(x: Array<string | number>): Array<string | number> {
  if (!shouldFormatDatesAsLabels(x)) return x;
  return x.map((value) => formatChartDate(String(value)));
}

export function BarChart({
  chart,
  loading = false,
  onPointClick,
}: {
  chart: ChartSpec | null | undefined;
  loading?: boolean;
  onPointClick?: (label: string) => void;
}) {
  if (loading) {
    return <ChartLoadingPlaceholder />;
  }
  if (!chart || chart.x.length === 0) return null;
  const formattedX = maybeFormatXTicks(chart.x);
  return (
    <Plot
      data={[
        {
          type: "bar",
          x: formattedX,
          y: chart.y,
          hovertemplate: "%{x}<br>%{y}<extra></extra>",
        },
      ]}
      layout={{
        title: chart.title,
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        margin: { l: 40, r: 20, t: 48, b: 120 },
        xaxis: { tickangle: -35 },
        yaxis: { title: chart.y_label ?? "" },
        height: 360,
      }}
      config={{ displayModeBar: false }}
      style={{ width: "100%" }}
      onClick={
        onPointClick
          ? ((event: Readonly<Plotly.PlotMouseEvent>) => {
              const point = event?.points?.[0];
              const label = point ? String(point.x ?? "") : "";
              if (label) onPointClick(label);
            }) as PlotParams["onClick"]
          : undefined
      }
    />
  );
}

export function LineChart({
  chart,
  loading = false,
}: {
  chart: { title: string; x: string[]; y: number[]; labels?: string[] } | null | undefined;
  loading?: boolean;
}) {
  if (loading) {
    return <ChartLoadingPlaceholder />;
  }
  if (!chart || chart.x.length === 0) return null;
  const formattedX = chart.x.map((value) => formatChartDate(value));
  const hovertext = chart.labels ?? chart.x.map((value) => formatChartDate(value));
  return (
    <Plot
      data={[
        {
          type: "scatter",
          mode: "lines+markers",
          x: formattedX,
          y: chart.y,
          hovertext,
          hoverinfo: "y+text",
        },
      ]}
      layout={{
        title: chart.title,
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        margin: { l: 40, r: 20, t: 48, b: 60 },
        height: 360,
      }}
      config={{ displayModeBar: false }}
      style={{ width: "100%" }}
    />
  );
}

export function SankeyChart({
  data,
  loading = false,
}: {
  data:
    | {
        node?: { label: string[]; color?: string[] };
        link?: { source: number[]; target: number[]; value: number[]; color?: string[] };
      }
    | null
    | undefined;
  loading?: boolean;
}) {
  const viewport = useChartViewport();
  if (loading) {
    const placeholderHeight = viewport === "compact" ? 460 : viewport === "wide" ? 580 : 500;
    return <ChartLoadingPlaceholder height={placeholderHeight} label="Loading flows chart…" />;
  }
  if (!data?.node?.label?.length || !data.link?.source?.length) return null;

  const nodePad = viewport === "compact" ? 10 : viewport === "wide" ? 18 : 14;
  const nodeThickness = viewport === "compact" ? 14 : viewport === "wide" ? 20 : 18;
  const chartHeight = viewport === "compact" ? 460 : viewport === "wide" ? 580 : 500;
  const fontSize = viewport === "compact" ? 10 : 12;
  const titleFontSize = viewport === "compact" ? 13 : 15;

  return (
    <ChartFrame minWidth={viewport === "compact" ? 320 : undefined}>
      <Plot
        data={[
          {
            type: "sankey",
            node: {
              label: data.node.label,
              color: data.node.color,
              pad: nodePad,
              thickness: nodeThickness,
            },
            link: {
              source: data.link.source,
              target: data.link.target,
              value: data.link.value,
              color: data.link.color,
            },
          },
        ]}
        layout={{
          title: { text: "Shares bought and sold", font: { size: titleFontSize } },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          margin: {
            l: viewport === "compact" ? 8 : 12,
            r: viewport === "compact" ? 8 : 12,
            t: viewport === "compact" ? 52 : 56,
            b: viewport === "compact" ? 12 : 16,
          },
          height: chartHeight,
          font: { size: fontSize },
          autosize: true,
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: "100%" }}
      />
    </ChartFrame>
  );
}

export function HorizontalBarChart({
  chart,
  loading = false,
  onPointClick,
}: {
  chart: { title: string; x: number[]; y: string[] } | null | undefined;
  loading?: boolean;
  onPointClick?: (label: string) => void;
}) {
  if (loading) {
    return <ChartLoadingPlaceholder />;
  }
  if (!chart || chart.x.length === 0) return null;
  return (
    <Plot
      data={[
        {
          type: "bar",
          orientation: "h",
          x: chart.x,
          y: chart.y,
          hovertemplate: "%{y}<br>%{x}<extra></extra>",
        },
      ]}
      layout={{
        title: chart.title,
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        margin: { l: 140, r: 20, t: 48, b: 40 },
        height: 360,
      }}
      config={{ displayModeBar: false }}
      style={{ width: "100%" }}
      onClick={
        onPointClick
          ? ((event: Readonly<Plotly.PlotMouseEvent>) => {
              const point = event?.points?.[0];
              const label = point ? String(point.y ?? "") : "";
              if (label) onPointClick(label);
            }) as PlotParams["onClick"]
          : undefined
      }
    />
  );
}

type GroupedBarSeries = {
  name: string;
  values: number[];
  color?: string;
};

type LaneMovement = {
  label: string;
  marker_color: string;
  marker_symbol?: string;
};

const LANE_LEGEND: Record<string, LaneMovement> = {
  "New position": { label: "New positions", marker_color: "#38bdf8", marker_symbol: "diamond" },
  "Closed position": { label: "Closed positions", marker_color: "#ef4444", marker_symbol: "x" },
  Increased: { label: "Increased", marker_color: "#22c55e", marker_symbol: "circle" },
  Decreased: { label: "Decreased", marker_color: "#f59e0b", marker_symbol: "triangle-down" },
};

type LaneRow = {
  Position?: string;
  Movement?: string;
  "Previous Shares"?: number;
  "New Shares"?: number;
  "Delta Shares"?: number;
  [key: string]: unknown;
};

type LanesChartProps = {
  chart: {
    title: string;
    rows: LaneRow[];
  } | null | undefined;
  loading?: boolean;
};

export function LanesChart({ chart, loading = false }: LanesChartProps) {
  const viewport = useChartViewport();
  if (loading) {
    return <ChartLoadingPlaceholder height={420} label="Loading lanes chart…" />;
  }
  if (!chart || !chart.rows?.length) return null;

  const positions = chart.rows
    .map((row) => String(row.Position ?? ""))
    .filter((label) => label.length > 0);
  if (!positions.length) return null;

  const colorByMovement: Record<string, string> = {
    "New position": "rgba(56, 189, 248, 0.48)",
    "Closed position": "rgba(239, 68, 68, 0.50)",
    Increased: "rgba(34, 197, 94, 0.44)",
    Decreased: "rgba(245, 158, 11, 0.48)",
  };
  const dashByMovement: Record<string, "solid" | "dot" | "dash"> = {
    "New position": "solid",
    "Closed position": "dash",
    Increased: "solid",
    Decreased: "dot",
  };

  const lineWidth = viewport === "compact" ? 4 : 5;
  const markerSize = viewport === "compact" ? 9 : viewport === "wide" ? 12 : 11;
  const movementMarkerSize = viewport === "compact" ? 11 : viewport === "wide" ? 14 : 13;
  const showDeltaLabels = viewport !== "compact";
  const rowHeight = viewport === "compact" ? 24 : viewport === "wide" ? 30 : 28;
  const chartHeight = Math.max(360, Math.min(980, 130 + positions.length * rowHeight));
  const rightMargin = viewport === "compact" ? 28 : viewport === "wide" ? 112 : 96;
  const titleFontSize = viewport === "compact" ? 13 : 15;

  const lineTraces: PlotParams["data"] = chart.rows.map((row) => {
    const movement = String(row.Movement ?? "Increased");
    return {
      type: "scatter",
      mode: "lines",
      x: [Number(row["Previous Shares"] ?? 0), Number(row["New Shares"] ?? 0)],
      y: [String(row.Position ?? ""), String(row.Position ?? "")],
      line: {
        color: colorByMovement[movement] ?? "rgba(120, 130, 145, 0.55)",
        width: lineWidth,
        dash: dashByMovement[movement] ?? "solid",
      },
      hoverinfo: "skip",
      showlegend: false,
    };
  });

  const previousTrace: PlotParams["data"][number] = {
    type: "scatter",
    name: "Previous quarter",
    y: positions,
    x: chart.rows.map((row) => Number(row["Previous Shares"] ?? 0)),
    mode: "markers",
    marker: {
      color: "rgba(14, 18, 26, 0.85)",
      line: { color: "rgba(155, 165, 180, 0.95)", width: 2 },
      size: markerSize,
      symbol: "circle-open",
    },
    customdata: chart.rows.map((row) => [
      String(row.Movement ?? ""),
      Number(row["Delta Shares"] ?? 0),
      Number(row["New Shares"] ?? 0),
    ]),
    hovertemplate:
      "Position: %{y}<br>Movement: %{customdata[0]}<br>Previous shares: %{x:,.0f}<br>New shares: %{customdata[2]:,.0f}<br>Delta shares: %{customdata[1]:+,.0f}<extra></extra>",
  };

  const seen = new Set<string>();
  const movementTraces: PlotParams["data"] = chart.rows.flatMap((row) => {
    const movement = String(row.Movement ?? "");
    if (!LANE_LEGEND[movement]) return [];
    if (seen.has(movement)) return [];
    seen.add(movement);
    const movementRows = chart.rows.filter((r) => String(r.Movement ?? "") === movement);
    return [
      {
        type: "scatter",
        name: LANE_LEGEND[movement].label,
        y: movementRows.map((r) => String(r.Position ?? "")),
        x: movementRows.map((r) => Number(r["New Shares"] ?? 0)),
        mode: showDeltaLabels ? "markers+text" : "markers",
        marker: {
          color: LANE_LEGEND[movement].marker_color,
          size: movementMarkerSize,
          symbol: LANE_LEGEND[movement].marker_symbol ?? "circle",
          line: { color: "rgba(255, 255, 255, 0.55)", width: 1 },
        },
        text: showDeltaLabels
          ? movementRows.map((r) => formatSignedQuantity(Number(r["Delta Shares"] ?? 0)))
          : undefined,
        textposition: showDeltaLabels ? "middle right" : undefined,
        textfont: showDeltaLabels ? { size: 10, color: "rgba(220, 225, 232, 0.92)" } : undefined,
        customdata: movementRows.map((r) => [
          movement,
          Number(r["Delta Shares"] ?? 0),
          Number(r["Previous Shares"] ?? 0),
        ]),
        hovertemplate:
          "Position: %{y}<br>Movement: %{customdata[0]}<br>Previous shares: %{customdata[2]:,.0f}<br>New shares: %{x:,.0f}<br>Delta shares: %{customdata[1]:+,.0f}<extra></extra>",
      } as unknown as PlotParams["data"][number],
    ];
  });

  const legendLayout =
    viewport === "compact"
      ? { orientation: "h" as const, yanchor: "top" as const, y: -0.22, xanchor: "left" as const, x: 0 }
      : { orientation: "h" as const, yanchor: "bottom" as const, y: 1.02, xanchor: "right" as const, x: 1 };

  const lanesMinWidth =
    viewport === "compact" ? 520 : viewport === "comfortable" ? 640 : undefined;

  return (
    <ChartFrame minWidth={lanesMinWidth}>
      <Plot
        data={[...lineTraces, previousTrace, ...movementTraces]}
        layout={{
          title: { text: chart.title, font: { size: titleFontSize } },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          margin: {
            l: viewport === "compact" ? 4 : 8,
            r: rightMargin,
            t: viewport === "compact" ? 72 : 64,
            b: viewport === "compact" ? 56 : 42,
          },
          xaxis: {
            title: { text: "Shares", font: { size: viewport === "compact" ? 11 : 12 } },
            rangemode: "tozero" as const,
            tickfont: { size: viewport === "compact" ? 10 : 11 },
          },
          yaxis: {
            title: { text: "" },
            categoryorder: "array" as const,
            categoryarray: positions.slice().reverse(),
            automargin: true,
            tickfont: { size: viewport === "compact" ? 10 : 11 },
          },
          hovermode: "closest" as const,
          legend: legendLayout,
          height: chartHeight,
          font: { size: viewport === "compact" ? 10 : 12 },
          autosize: true,
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: "100%" }}
      />
    </ChartFrame>
  );
}

function formatSignedQuantity(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "0";
  const sign = value > 0 ? "+" : "";
  return Number.isInteger(value) ? `${sign}${value.toLocaleString()}` : `${sign}${value.toFixed(2)}`;
}

type GroupedBarChartProps = {
  chart: {
    title: string;
    x: string[];
    series: GroupedBarSeries[];
    y_label?: string;
    barmode?: "group" | "stack";
  } | null | undefined;
  loading?: boolean;
};

export function GroupedBarChart({ chart, loading = false }: GroupedBarChartProps) {
  const viewport = useChartViewport();
  if (loading) {
    const placeholderHeight = viewport === "compact" ? 360 : viewport === "wide" ? 460 : 420;
    return <ChartLoadingPlaceholder height={placeholderHeight} />;
  }
  if (!chart || chart.x.length === 0 || !chart.series?.length) return null;

  const formattedX = maybeFormatXTicks(chart.x);
  const categoryCount = formattedX.length;

  // Thin x-axis ticks so labels never overlap, scaling targets by viewport.
  const targetLabels = viewport === "compact" ? 6 : viewport === "wide" ? 14 : 10;
  const tickInterval = Math.max(1, Math.ceil(categoryCount / targetLabels));

  const tickAngle = viewport === "compact" ? -55 : -35;
  const tickFontSize = viewport === "compact" ? 10 : 11;
  const titleFontSize = viewport === "compact" ? 13 : 15;
  const bottomMargin = viewport === "compact" ? 150 : 120;

  // Grow the chart height as the number of transitions grows so bars stay
  // legible instead of becoming hairlines.
  const baseHeight = viewport === "compact" ? 360 : viewport === "wide" ? 440 : 400;
  const perCategory = viewport === "compact" ? 5 : 7;
  const maxHeight = viewport === "compact" ? 560 : 760;
  const chartHeight = Math.min(
    maxHeight,
    Math.max(baseHeight, baseHeight + (categoryCount - 8) * perCategory),
  );

  const traces = chart.series.map((series) => ({
    type: "bar" as const,
    name: series.name,
    x: formattedX,
    y: series.values,
    marker: {
      color: series.color ?? TRANSITION_SERIES_COLORS[series.name] ?? DEFAULT_TRANSITION_COLOR,
    },
    hovertemplate: `%{x}<br>${series.name}: %{y}<extra></extra>`,
  }));

  // On narrow screens, give the plot a minimum width and let the frame scroll
  // horizontally instead of crushing bars into illegibility.
  const minWidth = viewport === "compact" ? 480 : undefined;

  return (
    <ChartFrame minWidth={minWidth}>
      <Plot
        data={traces}
        layout={{
          title: { text: chart.title, font: { size: titleFontSize } },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          margin: { l: 48, r: 20, t: 48, b: bottomMargin },
          xaxis: {
            tickangle: tickAngle,
            tickfont: { size: tickFontSize },
            dtick: tickInterval,
            automargin: true,
          },
          yaxis: { title: chart.y_label ?? "", automargin: true },
          barmode: chart.barmode ?? "group",
          legend: { orientation: "h", y: -0.28, x: 0, xanchor: "left" },
          height: chartHeight,
          font: { size: viewport === "compact" ? 10 : 12 },
          autosize: true,
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: "100%" }}
      />
    </ChartFrame>
  );
}