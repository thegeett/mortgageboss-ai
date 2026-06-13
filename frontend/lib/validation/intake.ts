/**
 * New-file intake form schema + select options (LP-32).
 *
 * Validation is **light / DRAFT-friendly** (ADR): the only real requirement is
 * the primary borrower's first + last name; every other field is optional and is
 * only format-checked **when a value is entered** (empty string = "not
 * provided"). This matches the model — a loan file can legitimately start sparse.
 */
import { z } from "zod";

// Optional-with-format: an empty string is valid (unset); a non-empty value must
// pass the format check.
const optionalEmail = z.union([
  z.literal(""),
  z.string().trim().email("Enter a valid email address"),
]);
const optionalSsn = z.union([
  z.literal(""),
  z
    .string()
    .trim()
    .regex(/^\d{3}-?\d{2}-?\d{4}$/, "Enter a 9-digit SSN"),
]);
const optionalState = z.union([
  z.literal(""),
  z
    .string()
    .trim()
    .regex(/^[A-Za-z]{2}$/, "Use a 2-letter state code"),
]);
const optionalZip = z.union([
  z.literal(""),
  z
    .string()
    .trim()
    .regex(/^\d{5}(-\d{4})?$/, "Enter a valid ZIP code"),
]);
const optionalAmount = z.union([
  z.literal(""),
  z
    .string()
    .trim()
    .regex(/^\d+(\.\d{1,2})?$/, "Enter a non-negative amount"),
]);

export const intakeSchema = z.object({
  // Borrower (primary) — name is the one real requirement.
  first_name: z.string().trim().min(1, "First name is required"),
  last_name: z.string().trim().min(1, "Last name is required"),
  middle_name: z.string().trim(),
  ssn: optionalSsn,
  date_of_birth: z.string(),
  email: optionalEmail,
  phone: z.string().trim(),
  marital_status: z.string(),
  // Property (all optional)
  address_line: z.string().trim(),
  address_line_2: z.string().trim(),
  city: z.string().trim(),
  state: optionalState,
  postal_code: optionalZip,
  property_type: z.string(),
  occupancy_type: z.string(),
  estimated_value: optionalAmount,
  purchase_price: optionalAmount,
  // Loan (all optional)
  loan_program: z.string(),
  loan_purpose: z.string(),
  loan_amount: optionalAmount,
  // Lender (all optional)
  lender_id: z.string(),
  loan_officer_name: z.string().trim(),
  loan_officer_email: optionalEmail,
});

export type IntakeFormValues = z.infer<typeof intakeSchema>;

export const INTAKE_DEFAULTS: IntakeFormValues = {
  first_name: "",
  last_name: "",
  middle_name: "",
  ssn: "",
  date_of_birth: "",
  email: "",
  phone: "",
  marital_status: "",
  address_line: "",
  address_line_2: "",
  city: "",
  state: "",
  postal_code: "",
  property_type: "",
  occupancy_type: "",
  estimated_value: "",
  purchase_price: "",
  loan_program: "",
  loan_purpose: "",
  loan_amount: "",
  lender_id: "",
  loan_officer_name: "",
  loan_officer_email: "",
};

export interface SelectOption {
  value: string;
  label: string;
}

export const MARITAL_STATUS_OPTIONS: SelectOption[] = [
  { value: "married", label: "Married" },
  { value: "unmarried", label: "Unmarried" },
  { value: "separated", label: "Separated" },
];

export const PROPERTY_TYPE_OPTIONS: SelectOption[] = [
  { value: "single_family", label: "Single family" },
  { value: "condo", label: "Condo" },
  { value: "townhouse", label: "Townhouse" },
  { value: "multi_family", label: "Multi-family" },
  { value: "manufactured", label: "Manufactured" },
  { value: "other", label: "Other" },
];

export const OCCUPANCY_TYPE_OPTIONS: SelectOption[] = [
  { value: "primary_residence", label: "Primary residence" },
  { value: "second_home", label: "Second home" },
  { value: "investment", label: "Investment" },
];

export const LOAN_PROGRAM_OPTIONS: SelectOption[] = [
  { value: "conventional", label: "Conventional" },
  { value: "fha", label: "FHA" },
];

export const LOAN_PURPOSE_OPTIONS: SelectOption[] = [
  { value: "purchase", label: "Purchase" },
  { value: "refinance", label: "Refinance" },
];
