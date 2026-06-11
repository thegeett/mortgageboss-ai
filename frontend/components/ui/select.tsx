import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";
import * as React from "react";

/**
 * A styled native `<select>` (LP-32). Native rather than a JS dropdown: fully
 * accessible and keyboard/mobile-friendly out of the box, and it integrates
 * cleanly with react-hook-form via a forwarded ref — no extra dependency for a
 * data-entry form with simple option lists.
 */
const Select = React.forwardRef<HTMLSelectElement, React.ComponentProps<"select">>(
  ({ className, children, ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          "flex h-10 w-full appearance-none rounded-md border border-input bg-background px-3 py-2 pr-9 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
          // Empty value (the placeholder option) reads as muted, like a placeholder.
          props.value === "" && "text-muted-foreground",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
    </div>
  ),
);
Select.displayName = "Select";

export { Select };
