import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../../hooks/use-auth";

export function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <div className="flex h-screen w-screen items-center justify-center bg-canvas text-ink-muted">Loading...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
