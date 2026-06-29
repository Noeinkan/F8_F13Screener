import { Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@mantine/core";
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

export function AppShellLayout() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const pageTitle = PAGE_TITLES[location.pathname] ?? "Dashboard";

  const dbState = useQuery({
    queryKey: ["db-state"],
    queryFn: () => apiGet<DbState>("/api/db/state"),
  });

  const handleRefresh = async () => {
    await apiPost("/api/cache/refresh");
    await queryClient.invalidateQueries();
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
