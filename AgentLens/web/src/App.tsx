import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/app-shell";
import { EmptyRoute } from "@/routes/empty";
import { RunDetailRoute } from "@/routes/run-detail";
import { RunsListRoute } from "@/routes/runs-list";
import { WorkspaceRoute } from "@/routes/workspace";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<RunsListRoute />} />
            <Route path="/empty" element={<EmptyRoute />} />
            <Route path="/runs/:runId" element={<RunDetailRoute />} />
            <Route path="/workspaces/:wsId" element={<WorkspaceRoute />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
