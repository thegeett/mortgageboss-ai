export const config = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  appName: "mortgageboss-ai",
  appVersion: "0.1.0",
} as const;
