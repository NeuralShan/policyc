import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";

import { ApiError } from "./api";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { ThemeProvider } from "./lib/theme";
import { AboutPage } from "./pages/AboutPage";
import { RootErrorBoundary, RouteErrorPage } from "./pages/ErrorPage";
import { GapCodesPage } from "./pages/GapCodesPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RunPage } from "./pages/RunPage";

const lazyPage = <K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) => ({
  lazy: async () => ({ Component: (await load())[name] }),
});

const router = createBrowserRouter([
  {
    element: <Layout />,
    errorElement: <RouteErrorPage />,
    HydrateFallback: () => <div className="p-10 text-center text-sm text-slate-500">Loading...</div>,
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/projects", element: <ProjectsPage /> },
      { path: "/projects/:projectId", element: <ProjectPage /> },
      { path: "/runs/:runId", element: <RunPage /> },
      // Lazy: keeps pdf.js out of the main bundle.
      { path: "/documents/:documentId", ...lazyPage(() => import("./pages/DocumentPage"), "DocumentPage") },
      { path: "/runs/:runId/ir-review", ...lazyPage(() => import("./pages/IRReviewPage"), "IRReviewPage") },
      { path: "/runs/:runId/graph", ...lazyPage(() => import("./pages/GraphPage"), "GraphPage") },
      { path: "/runs/:runId/diagnostics", ...lazyPage(() => import("./pages/DiagnosticsPage"), "DiagnosticsPage") },
      { path: "/runs/:runId/simulator", ...lazyPage(() => import("./pages/SimulatorPage"), "SimulatorPage") },
      { path: "/runs/:runId/tests", ...lazyPage(() => import("./pages/TestSuitePage"), "TestSuitePage") },
      { path: "/runs/:runId/testrun", ...lazyPage(() => import("./pages/TestRunPage"), "TestRunPage") },
      { path: "/runs/:runId/reality", ...lazyPage(() => import("./pages/RealityPage"), "RealityPage") },
      { path: "/runs/:runId/findings", lazy: async () => ({ Component: (await import("./pages/FindingsPage")).default }) },
      { path: "/gap-codes", element: <GapCodesPage /> },
      { path: "/about", element: <AboutPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Never retry client errors (404/401/403): they will not change.
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RootErrorBoundary>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </RootErrorBoundary>
  </StrictMode>,
);
