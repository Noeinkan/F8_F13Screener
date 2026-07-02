import { Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@mantine/core";
import { useState } from "react";
import { apiGet, apiPost } from "@/api/client";
import { SidebarNav } from "@/components/SidebarNav";
import { TopBar } from "@/components/TopBar";

const PAGE_TITLES: Record<string, string> = {
  "/": "Overview",
  "/fund-analysis": "Fund Analysis",
  "/consensus-trends": "Consensus Trends",
  "/holdings-search": "Holdings Search",
};

type DbState = {
  db_live: string;
  read_path: string;
  warning?: string | null;
};

type RefreshJob = {
  pid: number;
  started_at: number;
  finished_at?: number | null;
  exit_code?: number | null;
  error?: string | null;
  log_path?: string;
  duration_seconds?: number;
  running?: boolean;
};

type RefreshStatus = {
  running: boolean;
  current: RefreshJob | null;
  history: RefreshJob[];
};

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 30 * 60 * 1000; // 30 min, the full pipeline can be long

export function AppShellLayout() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const pageTitle = PAGE_TITLES[location.pathname] ?? "Dashboard";
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const dbState = useQuery({
    queryKey: ["db-state"],
    queryFn: () => apiGet<DbState>("/api/db/state"),
  });

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const started = await apiPost<RefreshJob>("/api/cache/refresh");
      setRefreshMessage(
        started.running
          ? `Refresh started (pid ${started.pid})…`
          : `Refresh already in progress (pid ${started.pid}).`,
      );

      const deadline = Date.now() + POLL_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        const status = await apiGet<RefreshStatus>("/api/cache/refresh/status");
        if (!status.running) {
          const finished = status.current ?? status.history.at(-1) ?? null;
          if (finished && finished.exit_code === 0) {
            setRefreshMessage(
              `Refresh complete in ${finished.duration_seconds ?? "?"}s.`,
            );
          } else if (finished && finished.exit_code !== null && finished.exit_code !== 0) {
            setRefreshMessage(
              `Refresh failed (exit ${finished.exit_code}). See log: ${finished.log_path ?? "n/a"}.`,
            );
          } else if (finished?.error) {
            setRefreshMessage(`Refresh error: ${finished.error}`);
          } else {
            setRefreshMessage("Refresh finished.");
          }
          break;
        }
        setRefreshMessage(
          `Refreshing (pid ${status.current?.pid ?? "?"})…`,
        );
      }

      await queryClient.invalidateQueries();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setRefreshMessage(`Refresh request failed: ${msg}`);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <AppShell
      navbar={{ width: 260, breakpoint: "sm" }}
      padding={0}
      styles={{
        main: {
          background: "transparent",
          minHeight: "100vh",
        },
        navbar: {
          background: "var(--f8-bg)",
          borderRight: "1px solid var(--f8-border)",
        },
      }}
    >
      <AppShell.Navbar p={0}>
        <SidebarNav
          dbLive={dbState.data?.db_live}
          readPath={dbState.data?.read_path}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          refreshMessage={refreshMessage}
        />
      </AppShell.Navbar>
      <AppShell.Main>
        <TopBar pageTitle={pageTitle} />
        <div style={{ padding: "1rem 1.25rem 2rem" }}>
          <Outlet />
        </div>
      </AppShell.Main>
    </AppShell>
  );
}
