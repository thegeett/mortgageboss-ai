// @vitest-environment jsdom
import { useCan } from "@/lib/auth/permissions";
import type { User } from "@/lib/auth/types";
import { useAuthStore } from "@/lib/stores/auth-store";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

const USER: User = {
  id: "u1",
  email: "pat@acme.com",
  first_name: "Pat",
  last_name: "P",
  roles: ["processor", "admin"],
  permissions: ["lenders.manage", "loan.create"],
  is_owner: false,
  company_id: "c1",
};

describe("useCan", () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: null, user: null, isInitializing: false });
  });

  it("is true for a key the user holds and false for one they do not", () => {
    useAuthStore.setState({ accessToken: "t", user: USER });
    expect(renderHook(() => useCan("lenders.manage")).result.current).toBe(true);
    expect(renderHook(() => useCan("users.manage")).result.current).toBe(false);
  });

  it("never reads roles: holding the admin role grants nothing the permissions do not", () => {
    useAuthStore.setState({ accessToken: "t", user: USER });
    expect(renderHook(() => useCan("company.settings.manage")).result.current).toBe(false);
  });

  it("is false, not a crash, for a user sent without permissions (an older backend)", () => {
    const { permissions: _dropped, ...older } = USER;
    useAuthStore.setState({ accessToken: "t", user: older as User });
    expect(renderHook(() => useCan("loan.create")).result.current).toBe(false);
  });

  it("is false while signed out", () => {
    expect(renderHook(() => useCan("loan.create")).result.current).toBe(false);
  });
});
