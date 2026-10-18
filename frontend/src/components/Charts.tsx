import type { PlotParams } from "react-plotly.js";
import type { ReactNode } from "react";
import { Plot } from "@/components/Plot";
import { Skeleton, Stack, Text } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { formatChartDate, formatDateValue } from "@/utils/dateFormat";

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

// One colour per movement on every chart (lanes, quarter activity, and the
// Sankey links built in src/web/charts.py MOVEMENT_STYLE): buying is blue/green,
// selling is red/amber.
const MOVEMENT_COLOR = {
  New: "#38bdf8",
  Closed: "#ef4444",
  Increased: "#22c55e",
  Decreased: "#f59e0b",
} as const;

const TRANSITION_SERIES_COLORS: Record<string, string> = MOVEMENT_COLOR;

const DEFAULT_TRANSITION_COLOR = "rgba(139, 148, 158, 0.7)";

// Two bars can share a label (Alphabet class A and C both read "ALPHABET INC").
// Plotly stacks equal categories onto one bar, so duplicates get their own
// key and the tick shows the plain label.
function uniqueCategories(labels: string[]): { keys: string[]; labelOf: (key: string) => string } {
  const hasDuplicates = new Set(labels).size !== labels.length;
  const keys = hasDuplicates ? labels.map((_, i) => `cat-${i}`) : labels;
  const byKey = new Map(keys.map((key, i) => [key, labels[i]]));
  return { keys, labelOf: (key) => byKey.get(key) ?? key };
}

const SELL_SERIES = new Set(["Closed", "Decreased"]);

const SERIES_LEGEND: Record<string, string> = {
  New: "New positions",
  Closed: "Closed positions",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "2026-05-15 → 2026-08-14" -> "Aug 2026": the filing that reported the change.
function shortTransitionLabel(category: string): string {
  const dates = category.match(/\d{4}-\d{2}-\d{2}/g);
  const last = dates?.[dates.length - 1];
  if (!last) return formatChartDate(category);
  const [year, month] = last.split("-");
  return `${MONTHS[Number(month) - 1] ?? month} ${year}`;
}

// "2026-05-15 → 2026-08-14" -> "15/05/2026 → 14/08/2026", for the hover.
function fullTransitionLabel(category: string): string {
  return category.replace(/\d{4}-\d{2}-\d{2}/g, (date) => formatDateValue(date));
}

// Ticks for an axis that runs both ways from zero, labelled without the minus
// sign: "10 closed" is a count, not a negative number.
function symmetricTicks(
  maxUp: number,
  maxDown: number,
): { tickvals: number[]; ticktext: string[]; range: [number, number] } {
  const span = Math.max(maxUp, maxDown, 1);
  const rough = span / 3;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step = ([1, 2, 5, 10].find((m) => m * pow >= rough) ?? 10) * pow;
  const tickvals: number[] = [];
  for (let v = -Math.ceil(maxDown / step) * step; v <= Math.ceil(maxUp / step) * step; v += step) {
    tickvals.push(Math.round(v * 1e6) / 1e6);
  }
  // Half a step of headroom at both ends: room for the "opened / closed" notes,
  // and the bottom tick no longer sits on the x-axis labels.
  const range: [number, number] = [tickvals[0] - step / 2, tickvals[tickvals.length - 1] + step / 2];
  return { tickvals, ticktext: tickvals.map((v) => Math.abs(v).toLocaleString()), range };
}

function compactNumber(abs: number): string {
  // parseFloat drops trailing zeros: 1.50 -> "1.5", 2.00 -> "2".
  if (abs >= 1e9) return `${parseFloat((abs / 1e9).toFixed(2))}B`;
  if (abs >= 1e6) return `${parseFloat((abs / 1e6).toFixed(2))}M`;
  if (abs >= 1e3) return `${parseFloat((abs / 1e3).toFixed(1))}K`;
  return abs.toFixed(0);
}

function isDollarLabel(label: string | undefined): boolean {
  return /usd|\$|value/i.test(label ?? "");
}

function formatBarValue(value: number, dollars: boolean): string {
  if (!Number.isFinite(value)) return "";
  const sign = value < 0 ? "−" : "";
  return `${sign}${dollars ? "$" : ""}${compactNumber(Math.abs(value))}`;
}

function shouldFormatDatesAsLabels(x: Array<string | number>): boolean {
  if (x.length === 0) return false;
  if (typeof x[0] === "number") return false;
  return x.every((value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value));
}

function maybeFormatXTicks(x: Array<string | number>): Array<string | number> {
  if (!shouldFormatDatesAsLabels(x)) return x;
  return x.map((value) => formatChartDate(String(value)));
}

// Month ("2024-05") or date ("2024-05-15") categories read left to right in
// time; anything else is a list of names, which reads better as rows.
function isTimeAxis(x: Array<string | number>): boolean {
  return x.length > 0 && x.every((value) => typeof value === "string" && /^\d{4}-\d{2}/.test(value));
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
  const viewport = useChartViewport();
  if (loading) {
    const placeholderHeight = viewport === "compact" ? 360 : viewport === "wide" ? 440 : 400;
    return <ChartLoadingPlaceholder height={placeholderHeight} />;
  }
  if (!chart || chart.x.length === 0) return null;
  const titleFontSize = viewport === "compact" ? 13 : 15;
  const clickHandler = (axis: "x" | "y") =>
    onPointClick
      ? (((event: Readonly<Plotly.PlotMouseEvent>) => {
          const point = event?.points?.[0];
          const label = point ? String(point[axis] ?? "") : "";
          if (label) onPointClick(label);
        }) as PlotParams["onClick"])
      : undefined;

  if (!isTimeAxis(chart.x)) {
    // Names as horizontal bars: full labels, no diagonal text eating a third
    // of the height. Largest at the top.
    const labels = [...chart.x].map(String).reverse();
    const values = [...chart.y].map(Number).reverse();
    const { keys, labelOf } = uniqueCategories(labels);
    // Snapshot top holdings carry no y_label but are dollars, like the Overview value chart.
    const dollars = chart.y_label === undefined || isDollarLabel(chart.y_label);
    const maxValue = Math.max(0, ...values.filter(Number.isFinite));
    const rowHeight = viewport === "compact" ? 24 : 28;
    const chartHeight = Math.max(260, 90 + labels.length * rowHeight);
    return (
      <Plot
        data={[
          {
            type: "bar",
            orientation: "h",
            x: values,
            y: keys,
            marker: { color: "#1e3a8a" },
            // The value on each bar, so nobody has to read it off the axis: inside
            // the bar when it fits, past its end when the bar is too short.
            text: values.map((value) => formatBarValue(value, dollars)),
            textposition: "auto",
            insidetextanchor: "end",
            insidetextfont: { size: 11, color: "#ffffff" },
            outsidetextfont: { size: 11, color: "#374151" },
            cliponaxis: false,
            hovertext: labels,
            hovertemplate: `%{hovertext}<br>%{x:${dollars ? "$,.0f" : ",.0f"}}<extra></extra>`,
            // insidetextfont/outsidetextfont are real Plotly bar options missing from @types/plotly.js.
          } as unknown as PlotParams["data"][number],
        ]}
        layout={{
          title: { text: chart.title, font: { size: titleFontSize } },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          margin: { l: 8, r: 20, t: 48, b: 40 },
          xaxis: {
            title: { text: chart.y_label ?? (dollars ? "Value (USD)" : "") },
            automargin: true,
            // "$1.5B" like the bar labels, not d3's "$1.5G".
            tickprefix: dollars ? "$" : "",
            exponentformat: "B",
            // Room past the bars for labels that land outside a short bar.
            range: [0, (maxValue || 1) * 1.1],
            gridcolor: "#eef0f3",
          },
          yaxis: {
            automargin: true,
            tickfont: { size: viewport === "compact" ? 10 : 11 },
            tickmode: "array",
            tickvals: keys,
            // Long fund names squeeze the bars in a half-width card; the hover has the full name.
            ticktext: labels.map((label) => (label.length > 30 ? `${label.slice(0, 29)}…` : label)),
            // Long fund and issuer names: cap the label column, the hover has the rest.
            ticklabeloverflow: "hide past domain",
          },
          height: chartHeight,
          font: { size: viewport === "compact" ? 10 : 12 },
          autosize: true,
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: "100%" }}
        onClick={
          onPointClick
            ? ((event: Readonly<Plotly.PlotMouseEvent>) => {
                const point = event?.points?.[0];
                const label = point ? labelOf(String(point.y ?? "")) : "";
                if (label) onPointClick(label);
              }) as PlotParams["onClick"]
            : undefined
        }
      />
    );
  }

  const formattedX = maybeFormatXTicks(chart.x);
  // "2023-08" -> "Aug 2023"; full dates keep their dd/mm/yyyy form.
  const tickLabels = formattedX.map((value) => {
    const month = /^(\d{4})-(\d{2})$/.exec(String(value));
    return month ? `${MONTHS[Number(month[2]) - 1] ?? month[2]} ${month[1]}` : String(value);
  });
  const categoryCount = formattedX.length;
  // This chart lives in a half-width card, so fewer labels than the screen
  // size alone would suggest; otherwise they run into each other.
  const targetLabels = viewport === "compact" ? 4 : 6;
  const tickInterval = Math.max(1, Math.ceil(categoryCount / targetLabels));
  // Count the thinning back from the end so the latest month is always labelled.
  const tickIndexes = formattedX
    .map((_, i) => i)
    .filter((i) => (categoryCount - 1 - i) % tickInterval === 0);
  const chartHeight = viewport === "compact" ? 300 : 360;

  return (
    <Plot
      data={[
        {
          type: "bar",
          x: formattedX,
          y: chart.y,
          marker: { color: "#1e3a8a" },
          hovertext: tickLabels,
          hovertemplate: "%{hovertext}<br>%{y:,}<extra></extra>",
        },
      ]}
      layout={{
        title: { text: chart.title, font: { size: titleFontSize } },
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        margin: { l: 48, r: 20, t: 48, b: 60 },
        xaxis: {
          type: "category",
          tickangle: 0,
          tickfont: { size: viewport === "compact" ? 10 : 11 },
          tickmode: "array",
          tickvals: tickIndexes.map((i) => formattedX[i]),
          ticktext: tickIndexes.map((i) => tickLabels[i]),
          automargin: true,
        },
        yaxis: { title: { text: chart.y_label ?? "" }, automargin: true },
        height: chartHeight,
        font: { size: viewport === "compact" ? 10 : 12 },
        autosize: true,
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%" }}
      onClick={clickHandler("x")}
    />
  );
}

export function LineChart({
  chart,
  loading = false,
  yLabel,
  valueFormat,
}: {
  chart: { title: string; x: string[]; y: number[]; labels?: string[] } | null | undefined;
  loading?: boolean;
  yLabel?: string;
  /** d3 format for the y axis and hover, e.g. "$~s" for dollars. */
  valueFormat?: string;
}) {
  if (loading) {
    return <ChartLoadingPlaceholder />;
  }
  if (!chart || chart.x.length === 0) return null;
  // ISO dates on a real date axis: filings are irregular, so spacing them by
  // time (not as evenly spaced labels) shows the gaps honestly.
  const hovertext = chart.labels ?? chart.x.map((value) => formatChartDate(value));
  const yFormat = valueFormat ?? ",~s";
  return (
    <Plot
      data={[
        {
          type: "scatter",
          mode: "lines+markers",
          x: chart.x,
          y: chart.y,
          line: { color: "#1e3a8a", width: 2 },
          marker: { size: 5 },
          hovertext,
          hovertemplate: `%{hovertext}<br>%{y:${yFormat}}<extra></extra>`,
        },
      ]}
      layout={{
        title: { text: chart.title, font: { size: 14 } },
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        margin: { l: 56, r: 20, t: 48, b: 40 },
        xaxis: { type: "date", tickformat: "%b %Y", automargin: true },
        yaxis: { title: { text: yLabel ?? "" }, tickformat: yFormat, rangemode: "tozero", automargin: true },
        height: 320,
        autosize: true,
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%" }}
    />
  );
}

export function SankeyChart({
  data,
  loading = false,
  onPointClick,
}: {
  data:
    | {
        node?: { label: string[]; color?: string[] };
        link?: { source: number[]; target: number[]; value: number[]; color?: string[] };
      }
    | null
    | undefined;
  loading?: boolean;
  onPointClick?: (label: string) => void;
}) {
  const viewport = useChartViewport();
  if (loading) {
    const placeholderHeight = viewport === "compact" ? 460 : viewport === "wide" ? 580 : 500;
    return <ChartLoadingPlaceholder height={placeholderHeight} label="Loading flows chart…" />;
  }
  if (!data?.node?.label?.length || !data.link?.source?.length) return null;

  const nodeCount = data.node.label.length;
  // Grow the chart with node count so small flows stay visible, but cap it
  // so the diagram doesn't take over the whole viewport. With 40 nodes the
  // wide-viewport chart reaches ~700px — taller than the old fixed 580px but
  // still fits in the folding area.
  const perNode = viewport === "compact" ? 5 : viewport === "wide" ? 8 : 6;
  const baseHeight = viewport === "compact" ? 420 : viewport === "wide" ? 480 : 440;
  const maxHeight = viewport === "compact" ? 540 : viewport === "wide" ? 700 : 620;
  const chartHeight = Math.min(maxHeight, Math.max(baseHeight, baseHeight + nodeCount * perNode));

  const nodePad = viewport === "compact" ? 6 : viewport === "wide" ? 12 : 10;
  const nodeThickness = viewport === "compact" ? 14 : viewport === "wide" ? 20 : 18;
  const fontSize = viewport === "compact" ? 10 : 12;
  const titleFontSize = viewport === "compact" ? 13 : 15;

  return (
    <ChartFrame minWidth={viewport === "compact" ? 320 : undefined}>
      <Text size="xs" c="dimmed" mb={4}>
        Shares flow left to right: from “Bought shares” into each position that grew, and from
        each position that shrank into “Sold shares”. Ribbon colour is the kind of move:{" "}
        {(
          [
            ["New position", MOVEMENT_COLOR.New],
            ["Increased", MOVEMENT_COLOR.Increased],
            ["Decreased", MOVEMENT_COLOR.Decreased],
            ["Closed position", MOVEMENT_COLOR.Closed],
          ] as const
        ).map(([name, color], i) => (
          <span key={name} style={{ whiteSpace: "nowrap" }}>
            {i > 0 ? " · " : ""}
            <span
              aria-hidden
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: 2,
                background: color,
                marginRight: 4,
                verticalAlign: "-1px",
              }}
            />
            {name}
          </span>
        ))}
        .
      </Text>
      <Plot
        data={[
          {
            type: "sankey",
            arrangement: "snap",
            node: {
              label: data.node.label,
              color: data.node.color,
              pad: nodePad,
              thickness: nodeThickness,
              line: { color: "rgba(60, 65, 75, 0.35)", width: 0.5 },
            },
            // Plotly's default halo behind node labels smears them into the
            // ribbons; plain dark text reads cleanly on the pale ribbons.
            textfont: { color: "#1f2937", shadow: "none" },
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
        onClick={
          onPointClick
            ? ((event: Readonly<Plotly.PlotMouseEvent>) => {
                const point = event?.points?.[0] as (Plotly.PlotDatum & { label?: string }) | undefined;
                if (!point) return;
                const label = String(point.label ?? "");
                if (!label) return;
                if (label === "Bought shares" || label === "Sold shares") return;
                onPointClick(label);
              }) as PlotParams["onClick"]
            : undefined
        }
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
  // Every Consensus chart counts funds (buying, selling, holding...).
  const values = chart.x.map(Number);
  const labels = chart.y.map(String);
  const { keys, labelOf } = uniqueCategories(labels);
  const maxValue = Math.max(0, ...values.filter(Number.isFinite));
  return (
    <Plot
      data={[
        {
          type: "bar",
          orientation: "h",
          x: values,
          y: keys,
          marker: { color: "#1e3a8a" },
          text: values.map((value) => value.toLocaleString()),
          textposition: "outside",
          textfont: { size: 11, color: "#374151" },
          cliponaxis: false,
          hovertext: labels,
          hovertemplate: "%{hovertext}<br>%{x:,} funds<extra></extra>",
        },
      ]}
      layout={{
        title: { text: chart.title, font: { size: 14 } },
        paper_bgcolor: "white",
        plot_bgcolor: "white",
        margin: { l: 8, r: 20, t: 48, b: 40 },
        // One row per bar, tall enough that Plotly labels every bar instead
        // of every other one.
        height: Math.max(260, 90 + chart.y.length * 22),
        xaxis: {
          title: { text: "Funds" },
          range: [0, (maxValue || 1) * 1.12],
          gridcolor: "#eef0f3",
        },
        yaxis: {
          automargin: true,
          tickmode: "array",
          tickvals: keys,
          ticktext: labels,
          tickfont: { size: 11 },
        },
        autosize: true,
      }}
      config={{ displayModeBar: false, responsive: true }}
      useResizeHandler
      style={{ width: "100%" }}
      onClick={
        onPointClick
          ? ((event: Readonly<Plotly.PlotMouseEvent>) => {
              const point = event?.points?.[0];
              const label = point ? labelOf(String(point.y ?? "")) : "";
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
  onPointClick?: (label: string) => void;
};

export function LanesChart({ chart, loading = false, onPointClick }: LanesChartProps) {
  const viewport = useChartViewport();
  if (loading) {
    return <ChartLoadingPlaceholder height={420} label="Loading lanes chart…" />;
  }
  if (!chart || !chart.rows?.length) return null;

  const rows = chart.rows.filter((row) => String(row.Position ?? "").length > 0);
  if (!rows.length) return null;
  const labelOf = (row: LaneRow) => String(row.Position ?? "");
  // Two rows can share a label (e.g. a warrant re-issued under a new CUSIP: one
  // closed, one new). Plotly would stack both on one lane, so each row gets its
  // own category key and the tick shows the plain label.
  const rowKey = new Map<LaneRow, string>(rows.map((row, i) => [row, `lane-${i}`]));
  const keyOf = (row: LaneRow) => rowKey.get(row) ?? labelOf(row);
  const positions = rows.map(keyOf);
  const labelByKey = new Map(rows.map((row) => [keyOf(row), labelOf(row)]));

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
  const rightMargin = viewport === "compact" ? 28 : 24;
  const titleFontSize = viewport === "compact" ? 13 : 15;
  const laneEnd = (row: LaneRow) =>
    Math.max(Number(row["Previous Shares"] ?? 0), Number(row["New Shares"] ?? 0));
  // Leave room right of the longest lane for its delta label, or Plotly clips it.
  const maxShares = Math.max(1, ...rows.map(laneEnd));
  const xRangeMax = maxShares * (showDeltaLabels ? 1.16 : 1.04);

  const lineTraces: PlotParams["data"] = rows.map((row) => {
    const movement = String(row.Movement ?? "Increased");
    return {
      type: "scatter",
      mode: "lines",
      x: [Number(row["Previous Shares"] ?? 0), Number(row["New Shares"] ?? 0)],
      y: [keyOf(row), keyOf(row)],
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
    x: rows.map((row) => Number(row["Previous Shares"] ?? 0)),
    mode: "markers",
    marker: {
      color: "rgba(14, 18, 26, 0.85)",
      line: { color: "rgba(155, 165, 180, 0.95)", width: 2 },
      size: markerSize,
      symbol: "circle-open",
    },
    customdata: rows.map((row) => [
      String(row.Movement ?? ""),
      Number(row["Delta Shares"] ?? 0),
      Number(row["New Shares"] ?? 0),
      labelOf(row),
    ]),
    hovertemplate:
      "Position: %{customdata[3]}<br>Movement: %{customdata[0]}<br>Previous shares: %{x:,.0f}<br>New shares: %{customdata[2]:,.0f}<br>Delta shares: %{customdata[1]:+,.0f}<extra></extra>",
  };

  const seen = new Set<string>();
  const movementTraces: PlotParams["data"] = rows.flatMap((row) => {
    const movement = String(row.Movement ?? "");
    if (!LANE_LEGEND[movement]) return [];
    if (seen.has(movement)) return [];
    seen.add(movement);
    const movementRows = rows.filter((r) => String(r.Movement ?? "") === movement);
    return [
      {
        type: "scatter",
        name: LANE_LEGEND[movement].label,
        y: movementRows.map(keyOf),
        x: movementRows.map((r) => Number(r["New Shares"] ?? 0)),
        mode: "markers",
        marker: {
          color: LANE_LEGEND[movement].marker_color,
          size: movementMarkerSize,
          symbol: LANE_LEGEND[movement].marker_symbol ?? "circle",
          line: { color: "rgba(255, 255, 255, 0.55)", width: 1 },
        },
        customdata: movementRows.map((r) => [
          movement,
          Number(r["Delta Shares"] ?? 0),
          Number(r["Previous Shares"] ?? 0),
          labelOf(r),
        ]),
        hovertemplate:
          "Position: %{customdata[3]}<br>Movement: %{customdata[0]}<br>Previous shares: %{customdata[2]:,.0f}<br>New shares: %{x:,.0f}<br>Delta shares: %{customdata[1]:+,.0f}<extra></extra>",
      } as unknown as PlotParams["data"][number],
    ];
  });

  // Delta labels sit past the right end of each lane, not beside the new-quarter
  // marker: on a decrease that marker is the left end, so the label ran over the
  // lane and the previous-quarter circle.
  const deltaLabelTrace: PlotParams["data"][number] | null = showDeltaLabels
    ? {
        type: "scatter",
        mode: "text",
        y: positions,
        x: rows.map(laneEnd),
        text: rows.map((r) => formatCompactSignedQuantity(Number(r["Delta Shares"] ?? 0))),
        textposition: "middle right",
        textfont: {
          size: 11,
          color: rows.map((r) => DELTA_LABEL_COLOR[String(r.Movement ?? "")] ?? "#4b5563"),
        },
        cliponaxis: false,
        hoverinfo: "skip",
        showlegend: false,
      } as unknown as PlotParams["data"][number]
    : null;

  // Title pinned to the top edge, legend in its own band just above the plot,
  // so the two never share a line.
  const legendLayout =
    viewport === "compact"
      ? { orientation: "h" as const, yanchor: "top" as const, y: -0.22, xanchor: "left" as const, x: 0 }
      : { orientation: "h" as const, yanchor: "bottom" as const, y: 1.01, xanchor: "left" as const, x: 0 };

  const lanesMinWidth =
    viewport === "compact" ? 520 : viewport === "comfortable" ? 640 : undefined;

  return (
    <ChartFrame minWidth={lanesMinWidth}>
      <Text size="xs" c="dimmed" mb={4}>
        Each row is one position. The hollow circle is the shares held last quarter, the
        coloured marker is the shares held now, and the bar between them is the change. The
        number at the end of each row is the net change in shares (hover for the exact figure).
      </Text>
      <Plot
        data={[...lineTraces, previousTrace, ...movementTraces, ...(deltaLabelTrace ? [deltaLabelTrace] : [])]}
        layout={{
          title: {
            text: chart.title,
            font: { size: titleFontSize },
            x: 0,
            xanchor: "left" as const,
            // Container, not plot area: long fund names would run off the right edge.
            xref: "container" as const,
            y: 1,
            yref: "container" as const,
            yanchor: "top" as const,
            pad: { t: 12, l: 8 },
          },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          margin: {
            l: viewport === "compact" ? 4 : 8,
            r: rightMargin,
            t: viewport === "compact" ? 48 : 104,
            b: viewport === "compact" ? 56 : 42,
          },
          xaxis: {
            title: { text: "Shares held", font: { size: viewport === "compact" ? 11 : 12 } },
            range: [0, xRangeMax],
            gridcolor: "#eef0f3",
            tickfont: { size: viewport === "compact" ? 10 : 11 },
          },
          yaxis: {
            title: { text: "" },
            categoryorder: "array" as const,
            categoryarray: positions.slice().reverse(),
            tickmode: "array" as const,
            tickvals: positions,
            ticktext: positions.map((key) => labelByKey.get(key) ?? key),
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
        onClick={
          onPointClick
            ? ((event: Readonly<Plotly.PlotMouseEvent>) => {
                const point = event?.points?.[0] as (Plotly.PlotDatum & { label?: string }) | undefined;
                if (!point) return;
                const key = String(point.y ?? point.label ?? "");
                const label = labelByKey.get(key) ?? key;
                if (!label) return;
                onPointClick(label);
              }) as PlotParams["onClick"]
            : undefined
        }
      />
    </ChartFrame>
  );
}

// Darker shades of the lane colours, legible as text on white.
const DELTA_LABEL_COLOR: Record<string, string> = {
  "New position": "#0369a1",
  "Closed position": "#b91c1c",
  Increased: "#15803d",
  Decreased: "#b45309",
};

// "+1.88M" reads at a glance where "+1,882,490" has to be counted; the exact
// figure stays in the hover.
function formatCompactSignedQuantity(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "0";
  return `${value > 0 ? "+" : "−"}${compactNumber(Math.abs(value))}`;
}

type GroupedBarChartProps = {
  chart: {
    title: string;
    x: string[];
    series: GroupedBarSeries[];
    y_label?: string;
  } | null | undefined;
  loading?: boolean;
  onPointClick?: (label: string) => void;
};

export function GroupedBarChart({ chart, loading = false, onPointClick }: GroupedBarChartProps) {
  const viewport = useChartViewport();
  if (loading) {
    const placeholderHeight = viewport === "compact" ? 360 : viewport === "wide" ? 460 : 420;
    return <ChartLoadingPlaceholder height={placeholderHeight} />;
  }
  if (!chart || chart.x.length === 0 || !chart.series?.length) return null;

  // x stays the raw category (e.g. "2026-05-15 → 2026-08-14") so clicks still
  // match a transition; only the tick text is shortened.
  const categories = chart.x.map(String);
  const categoryCount = categories.length;
  const fullLabels = categories.map(fullTransitionLabel);

  // Thin x-axis ticks so labels never overlap, scaling targets by viewport.
  const targetLabels = viewport === "compact" ? 6 : viewport === "wide" ? 14 : 10;
  const tickInterval = Math.max(1, Math.ceil(categoryCount / targetLabels));
  // Keep the newest quarter labelled: count the thinning back from the end.
  const tickIndexes = categories
    .map((_, i) => i)
    .filter((i) => (categoryCount - 1 - i) % tickInterval === 0);

  const tickFontSize = viewport === "compact" ? 10 : 11;
  const titleFontSize = viewport === "compact" ? 13 : 15;

  // Grow the chart height as the number of transitions grows so bars stay
  // legible instead of becoming hairlines.
  const baseHeight = viewport === "compact" ? 360 : viewport === "wide" ? 440 : 400;
  const perCategory = viewport === "compact" ? 5 : 7;
  const maxHeight = viewport === "compact" ? 560 : 760;
  const chartHeight = Math.min(
    maxHeight,
    Math.max(baseHeight, baseHeight + (categoryCount - 8) * perCategory),
  );

  // Up/down bars: what the fund opened or added to stacks above zero, what it
  // closed or trimmed stacks below, so each quarter reads as one column.
  const isSell = (name: string) => SELL_SERIES.has(name);
  const traces = chart.series.map((series) => ({
    type: "bar" as const,
    name: SERIES_LEGEND[series.name] ?? series.name,
    x: categories,
    y: series.values.map((value) => (isSell(series.name) ? -Math.abs(value) : value)),
    marker: {
      color: series.color ?? TRANSITION_SERIES_COLORS[series.name] ?? DEFAULT_TRANSITION_COLOR,
    },
    customdata: series.values.map((value, i) => [fullLabels[i], Math.abs(value)]),
    hovertemplate: `%{customdata[0]}<br>${series.name}: %{customdata[1]:,} positions<extra></extra>`,
  }));

  const stackTotal = (sell: boolean) =>
    Math.max(
      0,
      ...categories.map((_, i) =>
        chart.series
          .filter((series) => isSell(series.name) === sell)
          .reduce((sum, series) => sum + Math.abs(Number(series.values[i] ?? 0)), 0),
      ),
    );
  const { tickvals: yTickVals, ticktext: yTickText, range: yRange } = symmetricTicks(
    stackTotal(false),
    stackTotal(true),
  );

  // On narrow screens, give the plot a minimum width and let the frame scroll
  // horizontally instead of crushing bars into illegibility.
  const minWidth = viewport === "compact" ? 480 : undefined;

  const sideNote = (text: string, y: number, yanchor: "top" | "bottom") => ({
    text,
    xref: "paper" as const,
    yref: "paper" as const,
    x: 0,
    y,
    xanchor: "left" as const,
    yanchor,
    showarrow: false,
    font: { size: 11, color: "#6b7280" },
    bgcolor: "rgba(255, 255, 255, 0.8)",
  });

  return (
    <ChartFrame minWidth={minWidth}>
      <Plot
        data={traces}
        layout={{
          title: {
            text: chart.title,
            font: { size: titleFontSize },
            x: 0,
            xanchor: "left" as const,
            // Container, not plot area: long fund names would run off the right edge.
            xref: "container" as const,
            y: 1,
            yref: "container" as const,
            yanchor: "top" as const,
            pad: { t: 12, l: 8 },
          },
          paper_bgcolor: "white",
          plot_bgcolor: "white",
          margin: { l: 48, r: 20, t: viewport === "compact" ? 96 : 84, b: 48 },
          xaxis: {
            type: "category",
            tickangle: 0,
            tickfont: { size: tickFontSize },
            tickmode: "array",
            tickvals: tickIndexes.map((i) => categories[i]),
            ticktext: tickIndexes.map((i) => shortTransitionLabel(categories[i])),
            automargin: true,
          },
          yaxis: {
            title: { text: chart.y_label ?? "" },
            automargin: true,
            tickmode: "array",
            tickvals: yTickVals,
            range: yRange,
            ticktext: yTickText,
            zeroline: true,
            zerolinecolor: "#6b7280",
            zerolinewidth: 1.5,
            gridcolor: "#eef0f3",
          },
          barmode: "relative",
          legend: { orientation: "h", yanchor: "bottom", y: 1.02, x: 0, xanchor: "left" },
          annotations: [
            sideNote("▲ opened or added to", 1, "top"),
            sideNote("▼ closed or trimmed", 0, "bottom"),
          ],
          height: chartHeight,
          font: { size: viewport === "compact" ? 10 : 12 },
          autosize: true,
          hovermode: "closest",
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
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
    </ChartFrame>
  );
}