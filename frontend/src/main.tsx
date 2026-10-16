import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";

import { Layout } from "./components/Layout";
import { GapCodesPage } from "./pages/GapCodesPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RunPage } from "./pages/RunPage";

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <ProjectsPage /> },
      { path: "/projects/:projectId", element: <ProjectPage /> },
      { path: "/runs/:runId", element: <RunPage /> },
      {
        // Lazy: keeps pdf.js out of the main bundle.
        path: "/documents/:documentId",
        lazy: async () => ({ Component: (await import("./pages/DocumentPage")).DocumentPage }),
      },
      {
        path: "/runs/:runId/ir-review",
        lazy: async () => ({ Component: (await import("./pages/IRReviewPage")).IRReviewPage }),
      },
      {
        path: "/runs/:runId/graph",
        lazy: async () => ({ Component: (await import("./pages/GraphPage")).GraphPage }),
      },
      {
        path: "/runs/:runId/diagnostics",
        lazy: async () => ({
          Component: (await import("./pages/DiagnosticsPage")).DiagnosticsPage,
        }),
      },
      {
        path: "/runs/:runId/simulator",
        lazy: async () => ({
          Component: (await import("./pages/SimulatorPage")).SimulatorPage,
        }),
      },
      {
        path: "/runs/:runId/tests",
        lazy: async () => ({
          Component: (await import("./pages/TestSuitePage")).TestSuitePage,
        }),
      },
      {
        path: "/runs/:runId/testrun",
        lazy: async () => ({
          Component: (await import("./pages/TestRunPage")).TestRunPage,
        }),
      },
      {
        path: "/runs/:runId/reality",
        lazy: async () => ({
          Component: (await import("./pages/RealityPage")).RealityPage,
        }),
      },
      {
        path: "/runs/:runId/findings",
        lazy: async () => ({
          Component: (await import("./pages/FindingsPage")).default,
        }),
      },
      { path: "/gap-codes", element: <GapCodesPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
