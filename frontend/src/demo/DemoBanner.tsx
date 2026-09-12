import { useState } from "react";
import { Text } from "@mantine/core";
import { useDemoSession } from "@/demo/useDemoSession";
import { formatDateValue } from "@/utils/dateFormat";

const DISMISS_KEY = "f8-demo-banner-dismissed";

const BUILDS_URL = "https://noeinsolutions.com/builds.html";

function readDismissed(): boolean {
  try {
    return window.sessionStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * The line that keeps the demo honest: what the data is, how old it is, and
 * what has been switched off. Rendered only in demo mode, dismissible for the
 * length of the browser session.
 */
export function DemoBanner() {
  const session = useDemoSession();
  const [dismissed, setDismissed] = useState(readDismissed);

  if (session.data?.demo !== true || !session.data.authenticated) return null;
  if (dismissed) return null;

  const snapshot = session.data.snapshot;
  const asOf = snapshot.latestFilingDate
    ? formatDateValue(snapshot.latestFilingDate)
    : "an earlier date";
  const scale =
    snapshot.rows && snapshot.filings && snapshot.funds
      ? `${snapshot.rows.toLocaleString()} positions from ${snapshot.filings} filings by ${snapshot.funds} funds`
      : null;

  const dismiss = () => {
    setDismissed(true);
    try {
      window.sessionStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* a browser that refuses session storage just sees the banner again */
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        padding: "0.5rem 1.25rem",
        background: "#fff7e6",
        borderBottom: "1px solid #f0d9a8",
        color: "#6b4e16",
        fontSize: "0.82rem",
        lineHeight: 1.45,
      }}
    >
      <Text component="span" fw={700} style={{ fontSize: "0.82rem", whiteSpace: "nowrap" }}>
        Demo
      </Text>
      <Text component="span" style={{ fontSize: "0.82rem" }}>
        Frozen snapshot of SEC 13F filings up to <strong>{asOf}</strong> — it does
        not refresh{scale ? `. ${scale}` : ""}. Data refresh and the full CSV export
        are switched off; everything else is the real dashboard.{" "}
        <a href={BUILDS_URL} style={{ color: "#6b4e16", fontWeight: 700 }}>
          More builds →
        </a>
      </Text>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Hide the demo notice"
        style={{
          marginLeft: "auto",
          border: "none",
          background: "transparent",
          color: "#6b4e16",
          cursor: "pointer",
          fontSize: "1rem",
          lineHeight: 1,
          padding: "0.2rem 0.35rem",
        }}
      >
        ×
      </button>
    </div>
  );
}
