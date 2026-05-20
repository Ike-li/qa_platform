import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  timeout: 30_000,
  withCredentials: true,
});

let accessToken: string | null = null;

export const setAccessToken = (token: string | null) => {
  accessToken = token;
};

export const getAccessToken = () => accessToken;

let onAuthFailure: (() => void) | null = null;

export const setOnAuthFailure = (handler: () => void) => {
  onAuthFailure = handler;
};

let refreshPromise: Promise<string> | null = null;

const AUTH_PATHS = ["/auth/login", "/auth/refresh", "/auth/logout"];

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const requestPath = originalRequest?.url || "";

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !AUTH_PATHS.some((p) => requestPath.includes(p))
    ) {
      originalRequest._retry = true;
      try {
        if (!refreshPromise) {
          refreshPromise = axios
            .post("/api/v1/auth/refresh", null, { withCredentials: true })
            .then((res) => {
              setAccessToken(res.data.access_token);
              return res.data.access_token;
            })
            .finally(() => {
              refreshPromise = null;
            });
        }

        const token = await refreshPromise;
        originalRequest.headers.Authorization = `Bearer ${token}`;
        return api(originalRequest);
      } catch (refreshError) {
        setAccessToken(null);
        if (onAuthFailure) {
          onAuthFailure();
        }
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  }
);

export async function getArtifactDownloadUrl(artifactId: string): Promise<string> {
  const { data } = await api.get<{ download_url: string }>(`/artifacts/${artifactId}/download`);
  return data.download_url;
}

export default api;
