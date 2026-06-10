import axios, { type AxiosError } from "axios";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

// Request interceptor (will be expanded in LP-25 for JWT)
apiClient.interceptors.request.use(
  (config) => {
    // JWT token will be attached here in LP-25
    return config;
  },
  (error: AxiosError) => Promise.reject(error),
);

// Response interceptor for error normalization
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // Log error in development
    if (process.env.NODE_ENV === "development") {
      console.error("API error:", error.message, error.response?.data);
    }
    return Promise.reject(error);
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
