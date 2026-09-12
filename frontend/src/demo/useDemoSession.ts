import { useQuery } from "@tanstack/react-query";

export type DemoSnapshot = {
  latestFilingDate: string | null;
  capturedAt: string | null;
  quarters: string[];
  rows: number | null;
  funds: number | null;
  filings: number | null;
};

export type DemoSession = {
  demo: boolean;
  authenticated: boolean;
  snapshot: DemoSnapshot;
  limits: {
    sessionTtlMinutes: number;
    linkTtlMinutes: number;
    refreshDisabled: boolean;
    fullExportDisabled: boolean;
  };
};

const NOT_A_DEMO: DemoSession = {
  demo: false,
  authenticated: true,
  snapshot: {
    latestFilingDate: null,
    capturedAt: null,
    quarters: [],
    rows: null,
    funds: null,
    filings: null,
  },
  limits: {
    sessionTtlMinutes: 0,
    linkTtlMinutes: 0,
    refreshDisabled: false,
    fullExportDisabled: false,
  },
};

/**
 * Ask the API whether this build is running as the public demo.
 *
 * A 404 is the expected answer on a normal deployment, not a failure: with
 * DEMO_MODE off the demo routes are not registered at all. So this resolves to
 * `demo: false` and every caller behaves as it always has.
 */
export async function fetchDemoSession(): Promise<DemoSession> {
  const response = await fetch("/api/demo/session", { credentials: "include" });
  if (response.status === 404) return NOT_A_DEMO;
  if (!response.ok) return NOT_A_DEMO;
  return (await response.json()) as DemoSession;
}

export function useDemoSession() {
  return useQuery({
    queryKey: ["demo-session"],
    queryFn: fetchDemoSession,
    staleTime: Infinity,
    retry: false,
  });
}

/** True when the dashboard is running as the public demo (gate passed or not). */
export function useIsDemo(): boolean {
  return useDemoSession().data?.demo === true;
}
