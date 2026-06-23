import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

// Minimal CSS-only tooltip: wraps children, shows label on hover/focus.
export function Tooltip({
  label,
  children,
  className,
  side = "top",
  wide = false,
}: {
  label: ReactNode;
  children: ReactNode;
  className?: string;
  side?: "top" | "bottom";
  // `wide` wraps a longer description across multiple lines (fixed width)
  // instead of forcing a single no-wrap line.
  wide?: boolean;
}) {
  return (
    <span className={cn("group/tt relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 rounded-md border border-[var(--color-border-strong)] bg-[var(--color-elevated)] px-2 py-1 text-[11px] leading-snug text-[var(--color-fg)] opacity-0 shadow-lg transition-opacity duration-150 group-hover/tt:opacity-100 group-focus-within/tt:opacity-100",
          wide ? "w-60 whitespace-normal text-left" : "whitespace-nowrap",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        {label}
      </span>
    </span>
  );
}
