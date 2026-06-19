import { useCallback, type PointerEvent as ReactPointerEvent } from "react";
import { cn } from "../../lib/cn";

/**
 * A thin draggable divider between two panels.
 *
 * `axis="x"` is a vertical bar dragged left/right (resizes a column width);
 * `axis="y"` is a horizontal bar dragged up/down (resizes a row height).
 *
 * `sign` accounts for which side of the handle the resized panel sits on:
 *   +1 — the panel is BEFORE the handle (left/top): dragging toward the panel's
 *        far edge grows it.
 *   -1 — the panel is AFTER the handle (right/bottom): the delta is inverted so
 *        dragging away from the panel grows it.
 *
 * The handle snapshots the size at pointer-down and reports an absolute size to
 * `onChange` on each move, so clamping in the parent never drifts the cursor.
 */
export function ResizeHandle({
  axis,
  sign = 1,
  value,
  onChange,
  onReset,
  step = 24,
  min,
  max,
  className,
  "aria-label": ariaLabel,
}: {
  axis: "x" | "y";
  sign?: 1 | -1;
  value: number;
  onChange: (next: number) => void;
  onReset?: () => void;
  step?: number;
  min?: number;
  max?: number;
  className?: string;
  "aria-label"?: string;
}) {
  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      // Only the primary button starts a drag.
      if (e.button !== 0) return;
      e.preventDefault();
      const el = e.currentTarget;
      const pointerId = e.pointerId;
      const startPos = axis === "x" ? e.clientX : e.clientY;
      const startVal = value;

      // Pointer capture retargets EVERY subsequent event for this pointer
      // (move / up / cancel) to the handle, so the gesture's end is never lost
      // when the pointer leaves the window or the UA cancels a touch/pen drag.
      try {
        el.setPointerCapture(pointerId);
      } catch {
        /* capture unsupported — element-local listeners below still cover the
           common case */
      }

      const onMove = (ev: PointerEvent) => {
        const cur = axis === "x" ? ev.clientX : ev.clientY;
        onChange(startVal + (cur - startPos) * sign);
      };
      // Single teardown bound to up AND cancel AND lostpointercapture, so the
      // body cursor / user-select are ALWAYS restored and no listener leaks —
      // including touch/pen drags the browser ends with `pointercancel`.
      const end = () => {
        el.removeEventListener("pointermove", onMove);
        el.removeEventListener("pointerup", end);
        el.removeEventListener("pointercancel", end);
        el.removeEventListener("lostpointercapture", end);
        try {
          el.releasePointerCapture(pointerId);
        } catch {
          /* already released */
        }
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      el.addEventListener("pointermove", onMove);
      el.addEventListener("pointerup", end);
      el.addEventListener("pointercancel", end);
      el.addEventListener("lostpointercapture", end);
      // Keep the resize cursor + suppress text selection for the whole drag,
      // even when the pointer leaves the 4px handle.
      document.body.style.cursor = axis === "x" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";
    },
    [axis, sign, value, onChange],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const dec = axis === "x" ? "ArrowLeft" : "ArrowUp";
      const inc = axis === "x" ? "ArrowRight" : "ArrowDown";
      if (e.key === dec) {
        e.preventDefault();
        onChange(value - step * sign);
      } else if (e.key === inc) {
        e.preventDefault();
        onChange(value + step * sign);
      } else if (e.key === "Home" && min != null) {
        e.preventDefault();
        onChange(min);
      } else if (e.key === "End" && max != null) {
        e.preventDefault();
        onChange(max);
      }
    },
    [axis, sign, step, value, onChange, min, max],
  );

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      aria-label={ariaLabel}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      onPointerDown={onPointerDown}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className={cn(
        "group relative z-10 shrink-0 touch-none bg-[var(--color-border)] transition-colors hover:bg-[var(--color-accent)] focus-visible:bg-[var(--color-accent)]",
        axis === "x"
          ? "w-1 cursor-col-resize self-stretch"
          : "h-1 cursor-row-resize w-full",
        className,
      )}
      title={ariaLabel}
    >
      {/* Invisible, larger hit area so the 4px line is easy to grab. */}
      <span
        aria-hidden
        className={cn(
          "absolute",
          axis === "x"
            ? "-inset-x-1.5 inset-y-0"
            : "-inset-y-1.5 inset-x-0",
        )}
      />
    </div>
  );
}
