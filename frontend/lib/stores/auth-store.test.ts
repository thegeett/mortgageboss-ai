import type { User } from "@/lib/auth/types";
import { selectIsAuthenticated, useAuthStore } from "@/lib/stores/auth-store";
import { beforeEach, describe, expect, it } from "vitest";

const USER: User = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "processor@acme.com",
  first_name: "Pat",
  last_name: "Processor",
  role: "processor",
  company_id: "22222222-2222-2222-2222-222222222222",
};

describe("auth-store", () => {
  beforeEach(() => {
    // Reset to a known unauthenticated state between tests.
    useAuthStore.setState({ accessToken: null, user: null, isInitializing: true });
  });

  it("starts unauthenticated", () => {
    expect(selectIsAuthenticated(useAuthStore.getState())).toBe(false);
  });

  it("setAuth stores the token + user and is authenticated", () => {
    useAuthStore.getState().setAuth({ accessToken: "access-token-abc", user: USER });
    const state = useAuthStore.getState();
    expect(state.accessToken).toBe("access-token-abc");
    expect(state.user).toEqual(USER);
    expect(selectIsAuthenticated(state)).toBe(true);
  });

  it("clearAuth wipes the token + user and is unauthenticated", () => {
    useAuthStore.getState().setAuth({ accessToken: "access-token-abc", user: USER });
    useAuthStore.getState().clearAuth();
    const state = useAuthStore.getState();
    expect(state.accessToken).toBeNull();
    expect(state.user).toBeNull();
    expect(selectIsAuthenticated(state)).toBe(false);
  });

  it("finishInitializing flips the initializing flag off", () => {
    expect(useAuthStore.getState().isInitializing).toBe(true);
    useAuthStore.getState().finishInitializing();
    expect(useAuthStore.getState().isInitializing).toBe(false);
  });

  it("is not authenticated with a token but no user", () => {
    useAuthStore.setState({ accessToken: "orphan-token", user: null });
    expect(selectIsAuthenticated(useAuthStore.getState())).toBe(false);
  });
});
