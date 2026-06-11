"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { type BorrowerPayload, type PropertyPayload, submitIntake } from "@/lib/api/intake";
import { useLenders } from "@/lib/api/lenders";
import {
  INTAKE_DEFAULTS,
  type IntakeFormValues,
  LOAN_PROGRAM_OPTIONS,
  LOAN_PURPOSE_OPTIONS,
  MARITAL_STATUS_OPTIONS,
  OCCUPANCY_TYPE_OPTIONS,
  PROPERTY_TYPE_OPTIONS,
  type SelectOption,
  intakeSchema,
} from "@/lib/validation/intake";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { type Control, type FieldPath, useForm } from "react-hook-form";
import { toast } from "sonner";

/** Drop empty-string fields so we only send what was actually entered. */
function clean(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== ""));
}

function TextField({
  control,
  name,
  label,
  required,
  type = "text",
  placeholder,
  autoComplete,
}: {
  control: Control<IntakeFormValues>;
  name: FieldPath<IntakeFormValues>;
  label: string;
  required?: boolean;
  type?: string;
  placeholder?: string;
  autoComplete?: string;
}) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>
            {label}
            {required && <span className="text-destructive"> *</span>}
          </FormLabel>
          <FormControl>
            <Input type={type} placeholder={placeholder} autoComplete={autoComplete} {...field} />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

function SelectField({
  control,
  name,
  label,
  options,
  placeholder = "Select…",
}: {
  control: Control<IntakeFormValues>;
  name: FieldPath<IntakeFormValues>;
  label: string;
  options: SelectOption[];
  placeholder?: string;
}) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Select {...field}>
              <option value="">{placeholder}</option>
              {options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="border-gray-200/80 shadow-sm">
      <CardHeader>
        <CardTitle className="text-base font-semibold text-gray-900">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">{children}</CardContent>
    </Card>
  );
}

export function IntakeForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: lenders, isPending: lendersLoading } = useLenders();
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<IntakeFormValues>({
    resolver: zodResolver(intakeSchema),
    defaultValues: INTAKE_DEFAULTS,
  });

  const mutation = useMutation({ mutationFn: submitIntake });

  const onSubmit = async (values: IntakeFormValues) => {
    setFormError(null);

    const loanFile = clean({
      lender_id: values.lender_id,
      loan_program: values.loan_program,
      loan_purpose: values.loan_purpose,
      loan_officer_name: values.loan_officer_name,
      loan_officer_email: values.loan_officer_email,
    });
    const borrower: BorrowerPayload = {
      first_name: values.first_name,
      last_name: values.last_name,
      ...clean({
        middle_name: values.middle_name,
        ssn: values.ssn,
        date_of_birth: values.date_of_birth,
        email: values.email,
        phone: values.phone,
        marital_status: values.marital_status,
      }),
    };
    const propertyFields = clean({
      address_line: values.address_line,
      address_line_2: values.address_line_2,
      city: values.city,
      state: values.state,
      postal_code: values.postal_code,
      property_type: values.property_type,
      occupancy_type: values.occupancy_type,
      estimated_value: values.estimated_value,
      purchase_price: values.purchase_price,
    });
    const property: PropertyPayload | null =
      Object.keys(propertyFields).length > 0 ? propertyFields : null;

    let result: Awaited<ReturnType<typeof submitIntake>>;
    try {
      result = await mutation.mutateAsync({ loanFile, borrower, property });
    } catch {
      // File creation (the gate) failed — stay on the form so the user can retry.
      setFormError("We couldn't create the loan file. Check your connection and try again.");
      return;
    }

    // The file now exists; refresh the dashboard list and head to the file.
    queryClient.invalidateQueries({ queryKey: ["loan-files"] });
    if (result.warnings.length > 0) {
      toast.warning(
        `File ${result.file.display_id} created, but the ${result.warnings.join(
          " and ",
        )} couldn't be saved — you can add it on the file.`,
      );
    } else {
      toast.success(`Loan file ${result.file.display_id} created.`);
    }
    router.push(`/loan-files/${result.file.display_id}`);
  };

  const isSubmitting = form.formState.isSubmitting || mutation.isPending;

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        {formError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{formError}</span>
          </div>
        )}

        <Section title="Primary borrower" description="The main applicant on this loan file.">
          <TextField control={form.control} name="first_name" label="First name" required />
          <TextField control={form.control} name="last_name" label="Last name" required />
          <TextField control={form.control} name="middle_name" label="Middle name" />
          <TextField
            control={form.control}
            name="ssn"
            label="SSN"
            placeholder="XXX-XX-XXXX"
            autoComplete="off"
          />
          <TextField
            control={form.control}
            name="date_of_birth"
            label="Date of birth"
            type="date"
          />
          <SelectField
            control={form.control}
            name="marital_status"
            label="Marital status"
            options={MARITAL_STATUS_OPTIONS}
          />
          <TextField
            control={form.control}
            name="email"
            label="Email"
            type="email"
            placeholder="borrower@email.com"
          />
          <TextField control={form.control} name="phone" label="Phone" type="tel" />
        </Section>

        <Section title="Subject property" description="The property securing the loan (optional).">
          <TextField control={form.control} name="address_line" label="Street address" />
          <TextField control={form.control} name="address_line_2" label="Apt / unit" />
          <TextField control={form.control} name="city" label="City" />
          <TextField control={form.control} name="state" label="State" placeholder="CA" />
          <TextField
            control={form.control}
            name="postal_code"
            label="ZIP code"
            placeholder="94105"
          />
          <SelectField
            control={form.control}
            name="property_type"
            label="Property type"
            options={PROPERTY_TYPE_OPTIONS}
          />
          <SelectField
            control={form.control}
            name="occupancy_type"
            label="Occupancy"
            options={OCCUPANCY_TYPE_OPTIONS}
          />
          <TextField
            control={form.control}
            name="estimated_value"
            label="Estimated value"
            placeholder="450000"
          />
          <TextField
            control={form.control}
            name="purchase_price"
            label="Purchase price"
            placeholder="450000"
          />
        </Section>

        <Section title="Loan" description="Program, purpose, and amount (optional).">
          <SelectField
            control={form.control}
            name="loan_program"
            label="Loan program"
            options={LOAN_PROGRAM_OPTIONS}
          />
          <SelectField
            control={form.control}
            name="loan_purpose"
            label="Loan purpose"
            options={LOAN_PURPOSE_OPTIONS}
          />
          <TextField
            control={form.control}
            name="loan_amount"
            label="Loan amount"
            placeholder="360000"
          />
        </Section>

        <Section title="Lender" description="The lender and originating loan officer (optional).">
          <FormField
            control={form.control}
            name="lender_id"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Lender</FormLabel>
                <FormControl>
                  <Select {...field} disabled={lendersLoading}>
                    <option value="">
                      {lendersLoading
                        ? "Loading lenders…"
                        : lenders && lenders.length > 0
                          ? "Select a lender…"
                          : "No lenders configured"}
                    </option>
                    {lenders?.map((lender) => (
                      <option key={lender.id} value={lender.id}>
                        {lender.name}
                      </option>
                    ))}
                  </Select>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <TextField control={form.control} name="loan_officer_name" label="Loan officer name" />
          <TextField
            control={form.control}
            name="loan_officer_email"
            label="Loan officer email"
            type="email"
          />
        </Section>

        <div className="flex items-center justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => router.push("/dashboard")}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button type="submit" className="gap-2" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {isSubmitting ? "Creating…" : "Create file"}
          </Button>
        </div>
      </form>
    </Form>
  );
}
