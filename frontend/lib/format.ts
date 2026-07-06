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

/** A decimal-string amount → "$1,970.79" (cents kept — precision matters in the DTI calc). */
export function formatMoneyPrecise(value: string | null): string {
  if (value === null || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return value;
  return amount.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** A decimal-string percentage → "22.78%" (LP-76 DTI ratios). Null → "—". */
export function formatPercent(value: string | null): string {
  if (value === null || value === "") return "—";
  const pct = Number(value);
  if (Number.isNaN(pct)) return value;
  return `${pct.toFixed(2)}%`;
}
