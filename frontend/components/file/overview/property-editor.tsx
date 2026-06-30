"use client";

/**
 * Subject Property inline editor (LP-80.5) — reuses the shared EditableRow + the
 * existing PATCH /property endpoint. Audited with from→to values and marks
 * verification stale (the property drives LTV — a verification baseline input).
 */

import { EditableRow, type FieldDef } from "@/components/file/overview/editable-row";
import { useUpdateProperty } from "@/lib/api/overview-edit";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { PropertyPublic } from "@/lib/types/loan-file";
import { OCCUPANCY_TYPE_OPTIONS, PROPERTY_TYPE_OPTIONS } from "@/lib/validation/intake";
import { toast } from "sonner";

const PROPERTY_FIELDS: FieldDef[] = [
  { key: "address_line", label: "Address", kind: "text" },
  { key: "city", label: "City", kind: "text" },
  { key: "state", label: "State", kind: "text" },
  { key: "postal_code", label: "ZIP", kind: "text" },
  { key: "property_type", label: "Type", kind: "select", options: PROPERTY_TYPE_OPTIONS },
  { key: "occupancy_type", label: "Occupancy", kind: "select", options: OCCUPANCY_TYPE_OPTIONS },
  { key: "estimated_value", label: "Est. value", kind: "money" },
  { key: "purchase_price", label: "Purchase price", kind: "money" },
  // The MISMO valuation (LP-90) — the field the LTV's appraised basis reads first. Exposed
  // + editable so a processor can change it (previously hidden, silently shadowing est. value).
  { key: "valuation_amount", label: "Valuation amount", kind: "money" },
];

export function PropertyEditor({ fileId, property }: { fileId: string; property: PropertyPublic }) {
  const update = useUpdateProperty(fileId);

  return (
    <EditableRow
      fields={PROPERTY_FIELDS}
      initial={{
        address_line: property.address_line ?? "",
        city: property.city ?? "",
        state: property.state ?? "",
        postal_code: property.postal_code ?? "",
        property_type: property.property_type ?? "",
        occupancy_type: property.occupancy_type ?? "",
        estimated_value: property.estimated_value ?? "",
        purchase_price: property.purchase_price ?? "",
        valuation_amount: property.valuation_amount ?? "",
      }}
      onSave={(changed) =>
        update.mutate(changed, {
          onSuccess: () => toast.success("Property updated"),
          onError: (e) =>
            toast.error("Couldn't save the property", { description: getErrorMessage(e) }),
        })
      }
      busy={update.isPending}
    />
  );
}
