import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShellLayout } from "@/components/AppShell";
import { ConsensusTrendsPage } from "@/routes/ConsensusTrends";
import { FundAnalysisPage } from "@/routes/FundAnalysis";
import { HoldingsSearchPage } from "@/routes/HoldingsSearch";
import { OverviewPage } from "@/routes/Overview";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShellLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="fund-analysis" element={<FundAnalysisPage />} />
          <Route path="consensus-trends" element={<ConsensusTrendsPage />} />
          <Route path="holdings-search" element={<HoldingsSearchPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
