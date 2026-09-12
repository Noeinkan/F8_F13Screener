import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShellLayout } from "@/components/AppShell";
import { ChartLoading } from "@/components/LoadingState";
import { DemoGate } from "@/demo/DemoGate";

// Each page is its own chunk: opening Holdings Search does not download
// Plotly, and the first paint does not wait for pages nobody opened.
const OverviewPage = lazy(() =>
  import("@/routes/Overview").then((module) => ({ default: module.OverviewPage })),
);
const FundAnalysisPage = lazy(() =>
  import("@/routes/FundAnalysis").then((module) => ({ default: module.FundAnalysisPage })),
);
const ConsensusTrendsPage = lazy(() =>
  import("@/routes/ConsensusTrends").then((module) => ({ default: module.ConsensusTrendsPage })),
);
const HoldingsSearchPage = lazy(() =>
  import("@/routes/HoldingsSearch").then((module) => ({ default: module.HoldingsSearchPage })),
);

/** Suspense inside the shell, so the sidebar stays put while a page loads. */
function Page({ children }: { children: ReactNode }) {
  return <Suspense fallback={<ChartLoading label="Loading page…" />}>{children}</Suspense>;
}

export function App() {
  return (
    <DemoGate>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShellLayout />}>
            <Route index element={<Page><OverviewPage /></Page>} />
            <Route path="fund-analysis" element={<Page><FundAnalysisPage /></Page>} />
            <Route path="consensus-trends" element={<Page><ConsensusTrendsPage /></Page>} />
            <Route path="holdings-search" element={<Page><HoldingsSearchPage /></Page>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </DemoGate>
  );
}
