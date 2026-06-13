"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { useStatedFinancials } from "@/lib/api/mismo";
import { formatMoney } from "@/lib/format";
import type { StatedAsset, StatedBorrower, StatedLiability } from "@/lib/types/stated-financials";
import { format } from "date-fns";
import { Banknote, FileSpreadsheet, Info, Landmark, Wallet } from "lucide-react";

function importedOn(iso: string): string {
  try {
    return format(new Date(iso), "MMM d, yyyy");
  } catch {
    return "";
  }
}

/** A labelled value row. */
function Cell({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-gray-100 py-1.5 text-sm first:border-t-0">
      <span className="min-w-0 truncate text-gray-600">{label}</span>
      <span className="shrink-0 font-medium text-gray-900">{value}</span>
    </div>
  );
}

function SubSection({
  icon: Icon,
  title,
  count,
  children,
}: {
  icon: typeof Wallet;
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-5 first:mt-0">
      <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
        <Icon className="h-3.5 w-3.5" />
        {title}
        {count !== undefined && <span className="text-gray-300">· {count}</span>}
      </h4>
      {children}
    </section>
  );
}

function BorrowerBlock({ borrower }: { borrower: StatedBorrower }) {
  return (
    <div className="rounded-lg border border-gray-200/80 p-3">
      <p className="text-sm font-medium text-gray-900">
        {borrower.full_name || "Borrower"}
        {borrower.is_primary && <span className="ml-2 text-xs text-gray-400">Primary</span>}
      </p>
      {borrower.income_items.length > 0 && (
        <div className="mt-1.5">
          {borrower.income_items.map((inc, i) => (
            <Cell
              key={`${inc.income_type}-${i}`}
              label={`${inc.income_type ?? "Income"}${inc.employment_income ? " · employment" : ""}`}
              value={`${formatMoney(inc.monthly_amount)}/mo`}
            />
          ))}
        </div>
      )}
      {borrower.employers.length > 0 && (
        <p className="mt-2 text-xs text-gray-500">
          <span className="text-gray-400">Employers: </span>
          {borrower.employers.join(", ")}
        </p>
      )}
    </div>
  );
}

function LiabilityRow({ liability }: { liability: StatedLiability }) {
  return (
    <Cell
      label={`${liability.liability_type ?? "Liability"}${liability.holder_name ? ` · ${liability.holder_name}` : ""}`}
      value={
        <span className="tabular-nums">
          {formatMoney(liability.monthly_payment)}/mo
          <span className="ml-2 text-gray-400">{formatMoney(liability.unpaid_balance)} bal</span>
        </span>
      }
    />
  );
}

function AssetRow({ asset }: { asset: StatedAsset }) {
  return (
    <Cell
      label={`${asset.asset_type ?? "Asset"}${asset.holder_name ? ` · ${asset.holder_name}` : ""}`}
      value={<span className="tabular-nums">{formatMoney(asset.value)}</span>}
    />
  );
}

/**
 * "Application Data (Stated)" (LP-55) — the data MISMO import populated, the
 * visible proof the import worked: stated income/employers per borrower, the
 * file's liabilities and assets. **Display only** (editing is LP-56). Parse
 * warnings (a partial import) are surfaced here honestly + non-blocking. The
 * whole section is hidden for a file with no stated data (e.g. manual creation).
 */
export function StatedFinancialsSection({ fileId }: { fileId: string }) {
  const { data, isPending, isError, refetch } = useStatedFinancials(fileId);

  const hasData =
    !!data &&
    (data.mismo_import !== null ||
      data.liabilities.length > 0 ||
      data.assets.length > 0 ||
      data.borrowers.some((b) => b.income_items.length > 0 || b.employers.length > 0));

  // Nothing to show (manual file / no stated data) and not still loading → omit.
  if (!isPending && !isError && !hasData) return null;

  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <FileSpreadsheet className="h-4 w-4 text-gray-400" />
          Application data (stated)
          {data?.mismo_import && (
            <span className="text-xs font-normal text-gray-400">
              · imported from MISMO {importedOn(data.mismo_import.imported_at)}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent aria-busy={isPending}>
        {isPending ? (
          <>
            <output className="sr-only">Loading the imported application data</output>
            <SkeletonText lines={5} />
          </>
        ) : isError ? (
          <InlineErrorState
            message="Couldn't load the imported application data."
            onRetry={() => void refetch()}
          />
        ) : (
          data && (
            <>
              {/* Honest, non-blocking parse warnings. */}
              {data.mismo_import && data.mismo_import.warnings.length > 0 && (
                <div className="mb-4 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2.5 text-sm text-warning">
                  <p className="flex items-center gap-1.5 font-medium">
                    <Info className="h-4 w-4 shrink-0" />
                    Imported — a few fields need your attention
                  </p>
                  <ul className="mt-1.5 list-disc space-y-0.5 pl-7 text-xs">
                    {data.mismo_import.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                  <p className="mt-1.5 pl-7 text-xs text-warning/80">
                    The file was created — you can fill these in.
                  </p>
                </div>
              )}

              {data.borrowers.some((b) => b.income_items.length > 0 || b.employers.length > 0) && (
                <SubSection icon={Banknote} title="Income & employment">
                  <div className="space-y-2">
                    {data.borrowers.map((b) => (
                      <BorrowerBlock key={b.id} borrower={b} />
                    ))}
                  </div>
                </SubSection>
              )}

              {data.liabilities.length > 0 && (
                <SubSection icon={Landmark} title="Liabilities" count={data.liabilities.length}>
                  {data.liabilities.map((l, i) => (
                    <LiabilityRow key={`${l.liability_type}-${l.holder_name}-${i}`} liability={l} />
                  ))}
                </SubSection>
              )}

              {data.assets.length > 0 && (
                <SubSection icon={Wallet} title="Assets" count={data.assets.length}>
                  {data.assets.map((a, i) => (
                    <AssetRow key={`${a.asset_type}-${a.holder_name}-${i}`} asset={a} />
                  ))}
                </SubSection>
              )}

              {(data.loan_terms.note_rate_percent || data.loan_terms.amortization_months) && (
                <SubSection icon={Wallet} title="Loan terms (stated)">
                  {data.loan_terms.note_rate_percent && (
                    <Cell label="Note rate" value={`${data.loan_terms.note_rate_percent}%`} />
                  )}
                  {data.loan_terms.amortization_type && (
                    <Cell label="Amortization" value={data.loan_terms.amortization_type} />
                  )}
                  {data.loan_terms.amortization_months && (
                    <Cell label="Term" value={`${data.loan_terms.amortization_months} mo`} />
                  )}
                  {data.loan_terms.lien_priority && (
                    <Cell label="Lien" value={data.loan_terms.lien_priority} />
                  )}
                </SubSection>
              )}
            </>
          )
        )}
      </CardContent>
    </Card>
  );
}
