import { useCallback, useEffect, useState } from "react";

export interface Resizable {
  /** Current size in pixels (already clamped to [min, max]). */
  size: number;
  /** Set an absolute size; the value is clamped to [min, max]. */
  set: (v: number) => void;
  /** Restore the initial size. */
  reset: () => void;
  min: number;
  max: number;
}

/**
 * A persisted, clamped pixel size for a draggable panel edge.
 *
 * The size is stored in `localStorage` under `key` so a user's panel layout
 * survives reloads. `ResizeHandle` drives this via `set()` during a drag.
 */
export function useResizable(opts: {
  key: string;
  initial: number;
  min: number;
  max: number;
}): Resizable {
  const { key, initial, min, max } = opts;

  const clamp = useCallback(
    (v: number) => Math.min(max, Math.max(min, v)),
    [min, max],
  );

  const [size, setSize] = useState<number>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw != null) {
        const n = parseFloat(raw);
        if (Number.isFinite(n)) return Math.min(max, Math.max(min, n));
      }
    } catch {
      /* localStorage unavailable (private mode / SSR) — use the default */
    }
    return Math.min(max, Math.max(min, initial));
  });

  // Persist every committed size.
  useEffect(() => {
    try {
      localStorage.setItem(key, String(Math.round(size)));
    } catch {
      /* ignore */
    }
  }, [key, size]);

  const set = useCallback((v: number) => setSize(clamp(v)), [clamp]);
  const reset = useCallback(() => setSize(clamp(initial)), [clamp, initial]);

  return { size, set, reset, min, max };
}
