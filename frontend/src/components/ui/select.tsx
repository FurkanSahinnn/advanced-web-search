import { forwardRef, type SelectHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/cn";

export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <div className="relative">
    <select
      ref={ref}
      className={cn(
        "h-10 w-full appearance-none rounded-[var(--radius)] border border-[var(--color-border)] bg-[var(--color-surface-2)] pl-3 pr-9 text-sm text-[var(--color-fg)] transition-colors focus:border-[var(--color-accent)] focus:outline-none disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown
      className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-faint)]"
      aria-hidden
    />
  </div>
));
Select.displayName = "Select";
