import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./hooks/use-auth";
import { AppLayout } from "./components/layout/app-layout";
import { ProtectedRoute } from "./components/layout/protected-route";
import { ErrorBoundary } from "./components/layout/error-boundary";
import { Toaster } from "sonner";
import { Suspense, lazy } from "react";

// Lazy Pages
const Login = lazy(() => import("./pages/login"));
const Projects = lazy(() => import("./pages/projects/list"));
const ProjectDetail = lazy(() => import("./pages/projects/detail"));
const Runs = lazy(() => import("./pages/runs/list"));
const RunDetail = lazy(() => import("./pages/runs/detail"));
const Settings = lazy(() => import("./pages/settings"));

// Loading fallback
const PageLoader = () => (
  <div className="flex h-[50vh] w-full items-center justify-center text-ink-muted">
    <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
  </div>
);

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ErrorBoundary>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route path="/login" element={<Login />} />

                <Route element={<ProtectedRoute />}>
                  <Route element={<AppLayout />}>
                    <Route path="/" element={<Navigate to="/projects" replace />} />
                    <Route path="/projects" element={<Projects />} />
                    <Route path="/projects/:id" element={<ProjectDetail />} />
                    <Route path="/runs" element={<Runs />} />
                    <Route path="/runs/:id" element={<RunDetail />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="*" element={
                      <div className="flex h-[50vh] flex-col items-center justify-center text-center">
                        <h2 className="text-2xl font-semibold">404 - Not Found</h2>
                        <p className="mt-2 text-ink-subtle">The page you are looking for does not exist.</p>
                      </div>
                    } />
                  </Route>
                </Route>
              </Routes>
            </Suspense>
          </ErrorBoundary>
          <Toaster theme="dark" position="bottom-right" closeButton />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
