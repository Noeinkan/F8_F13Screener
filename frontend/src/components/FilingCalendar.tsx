import type { CSSProperties } from "react";
import { Text } from "@mantine/core";

/**
 * A 13F filing-cycle indicator for the sidebar.
 *
 * 13F-HR reports are quarterly and due 45 days after each quarter end, so the
 * dashboard's "latest filing" date legitimately stays flat for months between
 * deadlines (Q1 → ~15 May, Q2 → ~14 Aug, Q3 → ~14 Nov, Q4 → ~14 Feb). Funds
 * almost all file right at the deadline, so no new data appears until then.
 * This widget makes that cadence visible: what period is already filed, which
 * quarter is being awaited, and when to expect the next batch.
 *
 * Pure client-side date math — deterministic, no API call. It reflects the
 * regulatory calendar, not live DB state.
 */

type CyclePoint = {
  quarter: string;
  periodYear: number;
  monthsLabel: string;
  periodEnd: Date;
  deadline: Date;
};

const MS_DAY = 86_400_000;

// The four SEC 13F deadlines that land in `year` and the reporting period each
// one closes. Month indices are 0-based (Feb=1, May=4, Aug=7, Nov=10).
function cyclePointsForYear(year: number): CyclePoint[] {
  const defs = [
    { q: "Q4", py: year - 1, endM: 11, endD: 31, dM: 1, dD: 14, months: "Oct–Dec" },
    { q: "Q1", py: year, endM: 2, endD: 31, dM: 4, dD: 15, months: "Jan–Mar" },
    { q: "Q2", py: year, endM: 5, endD: 30, dM: 7, dD: 14, months: "Apr–Jun" },
    { q: "Q3", py: year, endM: 8, endD: 30, dM: 10, dD: 14, months: "Jul–Sep" },
  ];
  return defs.map((d) => ({
    quarter: d.q,
    periodYear: d.py,
    monthsLabel: d.months,
    periodEnd: new Date(d.py, d.endM, d.endD),
    deadline: new Date(year, d.dM, d.dD),
  }));
}

function fmtDate(d: Date): string {
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

const LABEL: CSSProperties = {
  fontSize: "0.62rem",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  fontWeight: 700,
  color: "var(--f8-muted)",
  marginBottom: 2,
};

export function FilingCalendar({ now = new Date() }: { now?: Date }) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  const points = [today.getFullYear() - 1, today.getFullYear(), today.getFullYear() + 1]
    .flatMap((y) => cyclePointsForYear(y))
    .sort((a, b) => a.deadline.getTime() - b.deadline.getTime());

  let latest: CyclePoint | undefined;
  let next: CyclePoint | undefined;
  for (const p of points) {
    if (p.deadline.getTime() <= today.getTime()) {
      latest = p;
    } else {
      next = p;
      break;
    }
  }
  if (!latest || !next) return null;

  const daysToNext = Math.max(
    0,
    Math.ceil((next.deadline.getTime() - today.getTime()) / MS_DAY),
  );
  const span = next.deadline.getTime() - latest.deadline.getTime();
  const progress =
    span > 0
      ? Math.min(100, Math.max(0, ((today.getTime() - latest.deadline.getTime()) / span) * 100))
      : 0;
  const quarterClosed = next.periodEnd.getTime() <= today.getTime();

  return (
    <div>
      <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb="sm">
        13F Filing Cycle
      </Text>

      <div
        style={{
          background: "var(--f8-surface)",
          border: "1px solid var(--f8-border)",
          borderRadius: "0.6rem",
          padding: "0.7rem 0.75rem",
        }}
      >
        {/* Latest period already on file */}
        <div style={LABEL}>Latest available</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontWeight: 700, color: "var(--f8-ink)" }}>
            {latest.quarter} {latest.periodYear}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--f8-muted)" }}>
            {latest.monthsLabel}
          </span>
          <span style={{ marginLeft: "auto", color: "#15803d", fontSize: "0.8rem" }}>✓</span>
        </div>
        <div style={{ fontSize: "0.72rem", color: "var(--f8-muted)" }}>
          filed by {fmtDate(latest.deadline)}
        </div>

        {/* Quarter currently being awaited */}
        <div style={{ ...LABEL, marginTop: "0.65rem" }}>Awaiting</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontWeight: 700, color: "var(--f8-ink)" }}>
            {next.quarter} {next.periodYear}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--f8-muted)" }}>
            {next.monthsLabel}
          </span>
        </div>
        <div style={{ fontSize: "0.72rem", color: "var(--f8-muted)" }}>
          quarter {quarterClosed ? "ended" : "ends"} {fmtDate(next.periodEnd)}
        </div>

        {/* Countdown to the next deadline */}
        <div style={{ ...LABEL, marginTop: "0.65rem" }}>Next data expected</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontWeight: 700, color: "var(--f8-accent)" }}>
            ~{fmtDate(next.deadline)}
          </span>
          <span style={{ marginLeft: "auto", fontSize: "0.75rem", color: "var(--f8-muted)" }}>
            in {daysToNext} {daysToNext === 1 ? "day" : "days"}
          </span>
        </div>
        <div
          style={{
            marginTop: 6,
            height: 5,
            borderRadius: 999,
            background: "var(--f8-border)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${progress}%`,
              height: "100%",
              background: "var(--f8-accent)",
              borderRadius: 999,
            }}
          />
        </div>

        <div style={{ marginTop: "0.6rem", fontSize: "0.68rem", color: "var(--f8-muted)", lineHeight: 1.35 }}>
          Funds almost all file on the deadline day, so the table stays flat
          until then — it is not stale.
        </div>
      </div>
    </div>
  );
}
