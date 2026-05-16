import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import api, { setAccessToken, setOnAuthFailure } from "../lib/api";

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (access_token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const navigate = useNavigate();

  const logout = useCallback(async () => {
    setAccessToken(null);
    setIsAuthenticated(false);
    try {
      await api.post("/auth/logout");
    } catch {
      // best-effort
    }
    navigate("/login", { replace: true });
  }, [navigate]);

  useEffect(() => {
    setOnAuthFailure(logout);
  }, [logout]);

  useEffect(() => {
    const initAuth = async () => {
      try {
        const response = await api.post("/auth/refresh", null, {
          withCredentials: true,
        });
        setAccessToken(response.data.access_token);
        setIsAuthenticated(true);
      } catch {
        setAccessToken(null);
      }
      setIsLoading(false);
    };

    initAuth();
  }, []);

  const login = (access_token: string) => {
    setAccessToken(access_token);
    setIsAuthenticated(true);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
