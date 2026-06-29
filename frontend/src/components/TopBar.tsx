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
    </div>
  );
}
