import { KOFI_URL } from "@/config/externalLinks";

type TopBarProps = {
  pageTitle: string;
};

export function TopBar({ pageTitle }: TopBarProps) {
  return (
    <div
      style={{
        height: 52,
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        padding: "0 1.25rem",
        background: "var(--f8-accent)",
        color: "#fff",
        borderBottom: "1px solid rgba(255,255,255,0.12)",
      }}
    >
      <strong style={{ fontSize: "1.05rem" }}>F8 13F Screener</strong>
      <span style={{ color: "rgba(255,255,255,0.75)", fontSize: "0.8rem", fontWeight: 600 }}>
        {pageTitle}
      </span>
      <a
        href={KOFI_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="donate-button"
        title="Support this project on Ko-fi"
        aria-label="Donate — support this project on Ko-fi"
        style={{
          marginLeft: "auto",
          display: "inline-flex",
          alignItems: "center",
          gap: "0.4rem",
          padding: "0.35rem 0.8rem",
          minHeight: 30,
          borderRadius: "0.4rem",
          border: "1px solid rgba(255, 191, 105, 0.7)",
          background: "rgba(255, 191, 105, 0.12)",
          color: "#ffbf69",
          fontSize: "0.85rem",
          fontWeight: 600,
          textTransform: "none",
          textDecoration: "none",
          letterSpacing: "0.01em",
          transition: "background-color 120ms ease, color 120ms ease, border-color 120ms ease",
        }}
      >
        <span aria-hidden="true">☕</span>
        Donate
      </a>
    </div>
  );
}
