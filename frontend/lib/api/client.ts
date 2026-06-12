import type { AuthTokenResponse } from "@/lib/auth/types";
import { useAuthStore } from "@/lib/stores/auth-store";
import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Backend auth endpoints (paths are also used for interceptor loop-protection). */
export const AUTH_LOGIN_PATH = "/api/v1/auth/login";
export const AUTH_REFRESH_PATH = "/api/v1/auth/refresh";
export const AUTH_LOGOUT_PATH = "/api/v1/auth/logout";
export const AUTH_ME_PATH = "/api/v1/auth/me";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  // withCredentials lets the browser send/receive the httpOnly refresh cookie
  // on refresh/logout. JS never reads the cookie itself.
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

/** Requests we must NOT auto-refresh on a 401, or we'd loop. */
function isRefreshExemptUrl(url: string | undefined): boolean {
  if (!url) return false;
  return url.includes(AUTH_LOGIN_PATH) || url.includes(AUTH_REFRESH_PATH);
}

/** axios config tagged so a retried request can't trigger a second refresh. */
interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

// --- Request interceptor: attach the current in-memory access token --------- //
apiClient.interceptors.request.use(
  (config) => {
    // Read the LIVE token via getState() — never a stale closure value.
    const token = useAuthStore.getState().accessToken;
    if (token) {
      config.headers.set("Authorization", `Bearer ${token}`);
    }
    return config;
  },
  (error: AxiosError) => Promise.reject(error),
);

// --- Single-flight refresh -------------------------------------------------- //
// Concurrent 401s share ONE in-flight refresh: the first 401 starts it, the
// rest await the same promise, then all retry with the new token.
let refreshPromise: Promise<string> | null = null;

/**
 * Refresh the access token using the httpOnly refresh cookie, store it, and
 * return it. De-duplicated: parallel callers get the same in-flight promise.
 * Used by the response interceptor and by the AuthProvider on load.
 */
export async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = apiClient
      .post<AuthTokenResponse>(AUTH_REFRESH_PATH)
      .then((response) => {
        const { access_token, user } = response.data;
        useAuthStore.getState().setAuth({ accessToken: access_token, user });
        return access_token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

/**
 * Hard redirect to the login page after the session is truly gone, preserving
 * where the user was headed and flagging *why* (so login shows a "session
 * expired" message instead of silently bouncing them — LP-46). A query param
 * survives the navigation reliably, unlike a toast the redirect would kill.
 */
function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname.startsWith("/login")) return;
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.assign(`/login?next=${next}&reason=session_expired`);
}

// --- Response interceptor: auto-refresh once on 401, then retry ------------- //
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    if (process.env.NODE_ENV === "development") {
      console.error("API error:", error.message, error.response?.data);
    }

    const original = error.config as RetryableRequestConfig | undefined;
    const status = error.response?.status;

    const shouldRefresh =
      status === 401 &&
      original !== undefined &&
      !original._retry &&
      !isRefreshExemptUrl(original.url);

    if (!shouldRefresh || original === undefined) {
      return Promise.reject(error);
    }

    original._retry = true;
    try {
      const token = await refreshAccessToken();
      original.headers.set("Authorization", `Bearer ${token}`);
      return apiClient(original);
    } catch (refreshError) {
      // Refresh itself failed — the session is truly gone. Clear and bounce.
      useAuthStore.getState().clearAuth();
      redirectToLogin();
      return Promise.reject(refreshError);
    }
  },
);

// Health check function (used by home page to verify connectivity)
export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  checks: {
    database: string;
    redis: string;
  };
}

export async function checkBackendHealth(): Promise<HealthResponse> {
  // Accept 503 (degraded) as a resolved response so the UI can render
  // per-dependency status. Only true network/transport errors reject.
  const response = await apiClient.get<HealthResponse>("/health", {
    validateStatus: (statusCode) => statusCode === 200 || statusCode === 503,
  });
  return response.data;
}
