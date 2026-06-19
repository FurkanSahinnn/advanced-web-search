import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export interface SliderProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {}

// A styled range input. Accent color via accent-color (modern browsers).
export const Slider = forwardRef<HTMLInputElement, SliderProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      type="range"
      className={cn(
        "h-1.5 w-full cursor-pointer appearance-none rounded-full bg-[var(--color-border-strong)] outline-none",
        "[accent-color:var(--color-accent)]",
        className,
      )}
      style={{ accentColor: "var(--color-accent)" }}
      {...props}
    />
  ),
);
Slider.displayName = "Slider";
