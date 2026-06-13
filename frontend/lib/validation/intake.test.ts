import { INTAKE_DEFAULTS, intakeSchema } from "@/lib/validation/intake";
import { describe, expect, it } from "vitest";

describe("intakeSchema", () => {
  it("accepts a minimal form (just borrower first + last name)", () => {
    const result = intakeSchema.safeParse({
      ...INTAKE_DEFAULTS,
      first_name: "Pat",
      last_name: "Buyer",
    });
    expect(result.success).toBe(true);
  });

  it("requires borrower first and last name", () => {
    const result = intakeSchema.safeParse(INTAKE_DEFAULTS); // both empty
    expect(result.success).toBe(false);
    if (!result.success) {
      const fields = result.error.issues.map((issue) => issue.path[0]);
      expect(fields).toContain("first_name");
      expect(fields).toContain("last_name");
    }
  });

  it("treats empty optional fields as valid (DRAFT-friendly)", () => {
    const result = intakeSchema.safeParse({
      ...INTAKE_DEFAULTS,
      first_name: "Pat",
      last_name: "Buyer",
      // ssn/email/state/zip/amount all "" — should be allowed
    });
    expect(result.success).toBe(true);
  });

  it("format-checks values only when provided", () => {
    const base = { ...INTAKE_DEFAULTS, first_name: "Pat", last_name: "Buyer" };
    expect(intakeSchema.safeParse({ ...base, email: "not-an-email" }).success).toBe(false);
    expect(intakeSchema.safeParse({ ...base, ssn: "12" }).success).toBe(false);
    expect(intakeSchema.safeParse({ ...base, state: "California" }).success).toBe(false);
    expect(intakeSchema.safeParse({ ...base, postal_code: "abc" }).success).toBe(false);
    expect(intakeSchema.safeParse({ ...base, estimated_value: "-5" }).success).toBe(false);

    // Valid provided values pass.
    expect(
      intakeSchema.safeParse({
        ...base,
        email: "pat@buyer.com",
        ssn: "123-45-6789",
        state: "CA",
        postal_code: "94105",
        estimated_value: "450000.00",
      }).success,
    ).toBe(true);
  });
});
