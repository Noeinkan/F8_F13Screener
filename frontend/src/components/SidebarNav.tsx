import { NavLink } from "react-router-dom";
import { Stack, Text } from "@mantine/core";

const PAGES = [
  { to: "/", label: "Overview" },
  { to: "/fund-analysis", label: "Fund Analysis" },
  { to: "/consensus-trends", label: "Consensus Trends" },
  { to: "/holdings-search", label: "Holdings Search" },
] as const;

type SidebarNavProps = {
  dbLive?: string;
  readPath?: string;
  onRefresh: () => void;
  refreshing?: boolean;
  refreshMessage?: string | null;
};

export function SidebarNav({
  dbLive,
  readPath,
  onRefresh,
  refreshing,
  refreshMessage,
}: SidebarNavProps) {
  return (
    <Stack gap="lg" p="md" style={{ background: "var(--f8-bg)", minHeight: "100%" }}>
      <div>
        <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb="sm">
          Pages
        </Text>
        <Stack gap={6}>
          {PAGES.map((page) => (
            <NavLink
              key={page.to}
              to={page.to}
              style={({ isActive }) => ({
                color: isActive ? "var(--f8-accent)" : "var(--f8-ink)",
                fontWeight: isActive ? 700 : 500,
                fontSize: "0.92rem",
              })}
            >
              {page.label}
            </NavLink>
          ))}
        </Stack>
      </div>

      <div>
        <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb="sm">
          Admin
        </Text>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          style={{
            width: "100%",
            background: refreshing ? "#94a3b8" : "var(--f8-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "0.5rem",
            padding: "0.55rem 0.75rem",
            fontWeight: 600,
            cursor: refreshing ? "wait" : "pointer",
          }}
        >
          {refreshing ? "Refreshing…" : "Refresh data"}
        </button>
        {refreshMessage ? (
          <Text
            size="xs"
            c="dimmed"
            mt="xs"
            style={{ wordBreak: "break-word" }}
          >
            {refreshMessage}
          </Text>
        ) : null}
        {dbLive ? (
          <Text size="xs" c="dimmed" mt="sm" style={{ wordBreak: "break-all" }}>
            DB live: {dbLive}
          </Text>
        ) : null}
        {readPath ? (
          <Text size="xs" c="dimmed" mt="xs" style={{ wordBreak: "break-all" }}>
            Read path: {readPath}
          </Text>
        ) : null}
      </div>

      <Text size="xs" c="dimmed" mt="auto">
        F8 13F Screener — hedge fund 13F tracker
      </Text>
    </Stack>
  );
}
