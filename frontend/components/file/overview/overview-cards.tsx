"use client";

import { LoanEditor } from "@/components/file/overview/loan-editor";
import { PropertyEditor } from "@/components/file/overview/property-editor";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SkeletonText } from "@/components/ui/skeleton";
import { useCreateProperty } from "@/lib/api/overview-edit";
import { getErrorMessage } from "@/lib/errors/api-error";
import { formatMoney, humanize } from "@/lib/format";
import { programLabel, purposeLabel } from "@/lib/loan-files/labels";
import type { BorrowerDetail } from "@/lib/types/borrower";
import type { LoanFileDetail } from "@/lib/types/loan-file";
import { Building2, Check, Landmark, Pencil, Plus, TriangleAlert, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

function OverviewCard({
  title,
  icon: Icon,
  loading = false,
  action,
  children,
}: {
  title: string;
  icon: LucideIcon;
  loading?: boolean;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <Icon className="h-4 w-4 text-gray-400" />
          {title}
        </CardTitle>
        {action}
      </CardHeader>
      <CardContent className="pt-0" aria-busy={loading}>
        {loading && <output className="sr-only">Loading {title.toLowerCase()}</output>}
        {children}
      </CardContent>
    </Card>
  );
}

/** The shared Edit/Done toggle used by the editable cards. */
function EditToggle({ editing, onToggle }: { editing: boolean; onToggle: () => void }) {
  return (
    <Button
      type="button"
      size="sm"
      variant={editing ? "default" : "outline"}
      onClick={onToggle}
      className="h-7 gap-1.5 text-xs"
    >
      {editing ? <Check className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
      {editing ? "Done" : "Edit"}
    </Button>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-t border-gray-100 py-1.5 text-sm first:border-t-0">
      <span className="shrink-0 text-gray-500">{label}</span>
      <span className="max-w-[62%] truncate text-right font-medium text-gray-900">{value}</span>
    </div>
  );
}

function CardSkeleton() {
  // Four label/value rows — roughly the height of a populated card body.
  return <SkeletonText lines={4} widths={["w-full", "w-5/6", "w-4/6", "w-3/4"]} className="py-1" />;
}

function CardEmpty({ message }: { message: string }) {
  return <p className="py-4 text-sm text-gray-400">{message}</p>;
}

function CardError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center gap-2 py-4 text-sm text-gray-500">
      <TriangleAlert className="h-4 w-4 shrink-0 text-destructive" />
      <span>{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
        >
          Retry
        </button>
      )}
    </div>
  );
}

interface CardState {
  isPending: boolean;
  isError: boolean;
  onRetry?: () => void;
}

export function BorrowerCard({
  borrowers,
  isPending,
  isError,
  onRetry,
}: CardState & { borrowers: BorrowerDetail[] | undefined }) {
  return (
    <OverviewCard title="Borrowers" icon={Users} loading={isPending}>
      {isPending ? (
        <CardSkeleton />
      ) : isError ? (
        <CardError message="Couldn't load borrowers." onRetry={onRetry} />
      ) : !borrowers || borrowers.length === 0 ? (
        <CardEmpty message="No borrower added yet." />
      ) : (
        borrowers.map((borrower, index) => (
          <div key={borrower.id} className={index > 0 ? "mt-3 border-t border-gray-100 pt-3" : ""}>
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-900">
                {borrower.first_name} {borrower.last_name}
              </span>
              {borrower.is_primary && (
                <Badge variant="secondary" className="px-1.5 py-0 text-[10px] font-medium">
                  Primary
                </Badge>
              )}
            </div>
            <div className="mt-1">
              <Row label="SSN" value={borrower.masked_ssn || "—"} />
              <Row label="Marital status" value={humanize(borrower.marital_status)} />
              <Row label="Email" value={borrower.email || "—"} />
              <Row label="Phone" value={borrower.phone || "—"} />
            </div>
          </div>
        ))
      )}
    </OverviewCard>
  );
}

export function PropertyCard({
  file,
  isPending,
  isError,
  onRetry,
}: CardState & { file: LoanFileDetail | undefined }) {
  const [editing, setEditing] = useState(false);
  const createProperty = useCreateProperty(file?.id ?? "");
  const property = file?.property;
  const canEdit = !isPending && !isError && !!file;

  return (
    <OverviewCard
      title="Subject property"
      icon={Building2}
      loading={isPending}
      action={
        canEdit && property ? (
          <EditToggle editing={editing} onToggle={() => setEditing((e) => !e)} />
        ) : undefined
      }
    >
      {isPending ? (
        <CardSkeleton />
      ) : isError ? (
        <CardError message="Couldn't load the property." onRetry={onRetry} />
      ) : !property ? (
        <div className="py-3">
          <CardEmpty message="No property added yet." />
          {file && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="gap-1.5"
              disabled={createProperty.isPending}
              onClick={() =>
                createProperty.mutate(
                  {},
                  {
                    onSuccess: () => {
                      toast.success("Property added");
                      setEditing(true);
                    },
                    onError: (e) =>
                      toast.error("Couldn't add the property", {
                        description: getErrorMessage(e),
                      }),
                  },
                )
              }
            >
              <Plus className="h-3.5 w-3.5" /> Add property
            </Button>
          )}
        </div>
      ) : editing && file ? (
        <PropertyEditor fileId={file.id} property={property} />
      ) : (
        <div>
          <Row
            label="Address"
            value={
              property.address_line
                ? [property.address_line, property.city, property.state, property.postal_code]
                    .filter(Boolean)
                    .join(", ")
                : "—"
            }
          />
          <Row label="Type" value={humanize(property.property_type)} />
          <Row label="Occupancy" value={humanize(property.occupancy_type)} />
          <Row label="Estimated value" value={formatMoney(property.estimated_value)} />
          <Row label="Purchase price" value={formatMoney(property.purchase_price)} />
          {/* The MISMO valuation (LP-90) — the field the LTV's appraised basis reads first. */}
          <Row label="Valuation amount" value={formatMoney(property.valuation_amount)} />
        </div>
      )}
    </OverviewCard>
  );
}

export function LoanCard({
  file,
  isPending,
  isError,
  onRetry,
}: CardState & { file: LoanFileDetail | undefined }) {
  const [editing, setEditing] = useState(false);
  const canEdit = !isPending && !isError && !!file;

  return (
    <OverviewCard
      title="Loan"
      icon={Landmark}
      loading={isPending}
      action={
        canEdit ? (
          <EditToggle editing={editing} onToggle={() => setEditing((e) => !e)} />
        ) : undefined
      }
    >
      {isPending ? (
        <CardSkeleton />
      ) : isError || !file ? (
        <CardError message="Couldn't load loan details." onRetry={onRetry} />
      ) : editing ? (
        <LoanEditor file={file} />
      ) : (
        <div>
          <Row label="Status" value={<StatusBadge status={file.status} />} />
          <Row label="Program" value={programLabel(file.loan_program)} />
          <Row label="Purpose" value={purposeLabel(file.loan_purpose)} />
          <Row label="Amount" value={formatMoney(file.loan_amount)} />
          <Row
            label="Target lender"
            value={
              file.lender_name || (
                // The lender selects the verification overlay (LP-80) — make setting it obvious.
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="font-medium text-primary underline-offset-2 hover:underline"
                >
                  Set lender
                </button>
              )
            }
          />
          <Row label="Loan officer" value={file.loan_officer_name || "—"} />
          <Row label="LO email" value={file.loan_officer_email || "—"} />
        </div>
      )}
    </OverviewCard>
  );
}
