import { Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@mantine/core";
import { useState } from "react";
import { apiGet, apiPost, describeError } from "@/api/client";
import { SidebarNav } from "@/components/SidebarNav";
import { TopBar } from "@/components/TopBar";
import { DemoBanner } from "@/demo/DemoBanner";
import { useIsDemo } from "@/demo/useDemoSession";

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
// After a failed status check, wait longer: an API restart takes seconds.
const POLL_RETRY_INTERVAL_MS = 5000;
// The refresh job keeps running on the server whatever happens to one status
// request, so a blip must not end the polling. Six misses in a row (~30 s of
// silence) is an outage, not a blip.
const MAX_CONSECUTIVE_POLL_FAILURES = 6;
const POLL_TIMEOUT_MS = 30 * 60 * 1000; // 30 min, the full pipeline can be long

function errorSummary(err: unknown): string {
  const { message, status, detail } = describeError(err);
  return [message, status ? `HTTP ${status}` : null, detail].filter(Boolean).join(" · ");
}

export function AppShellLayout() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const isDemo = useIsDemo();
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
      let consecutiveFailures = 0;
      let outcome: "finished" | "lost-contact" | "timed-out" = "timed-out";
      while (Date.now() < deadline) {
        await new Promise((r) =>
          setTimeout(r, consecutiveFailures > 0 ? POLL_RETRY_INTERVAL_MS : POLL_INTERVAL_MS),
        );
        let status: RefreshStatus;
        try {
          status = await apiGet<RefreshStatus>("/api/cache/refresh/status");
          consecutiveFailures = 0;
        } catch (pollErr) {
          consecutiveFailures += 1;
          if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
            setRefreshMessage(
              `Lost contact with the API: ${consecutiveFailures} status checks in a row failed ` +
                `(${errorSummary(pollErr)}). The refresh may still be running on the server — ` +
                "reload the page in a few minutes to see the new data.",
            );
            outcome = "lost-contact";
            break;
          }
          setRefreshMessage(
            `Refreshing… status check failed (${consecutiveFailures}/${MAX_CONSECUTIVE_POLL_FAILURES}), retrying.`,
          );
          continue;
        }
        if (!status.running) {
          outcome = "finished";
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

      if (outcome === "timed-out") {
        setRefreshMessage(
          `Stopped watching after ${POLL_TIMEOUT_MS / 60_000} minutes; the refresh is still running on the server. ` +
            "Reload the page later to see the new data.",
        );
      }
      // With the API unreachable, refetching every query would only turn each
      // page into an error; the user reloads once the API is back.
      if (outcome !== "lost-contact") {
        await queryClient.invalidateQueries();
      }
    } catch (err) {
      setRefreshMessage(`Refresh request failed: ${errorSummary(err)}`);
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
          dbLive={isDemo ? undefined : dbState.data?.db_live}
          readPath={isDemo ? undefined : dbState.data?.read_path}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          refreshMessage={refreshMessage}
          hideRefresh={isDemo}
        />
      </AppShell.Navbar>
      <AppShell.Main>
        <DemoBanner />
        <TopBar pageTitle={pageTitle} />
        <div style={{ padding: "1rem 1.25rem 2rem" }}>
          <Outlet />
        </div>
      </AppShell.Main>
    </AppShell>
  );
}
