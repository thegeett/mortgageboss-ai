/** Small display formatters (LP-34). */

/** A decimal-string amount (Pydantic serialises Decimal as a string) → "$360,000". */
export function formatMoney(value: string | null): string {
  if (!value) return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return value;
  return amount.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

/** A human label for an enum-ish value: "primary_residence" → "Primary residence". */
export function humanize(value: string | null): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
