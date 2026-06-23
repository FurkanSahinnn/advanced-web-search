import { HelpCircle } from "lucide-react";
import type { ScoreWeights as Weights } from "../lib/types";
import { useLang } from "../lib/i18n";
import { Slider } from "./ui/slider";
import { Tooltip } from "./ui/tooltip";
import { cn } from "../lib/cn";

const KEYS: (keyof Weights)[] = [
  "relevance",
  "authority",
  "recency",
  "citation_impact",
  "evidence",
];

export function ScoreWeights({
  value,
  onChange,
  className,
}: {
  value: Weights;
  onChange: (w: Weights) => void;
  className?: string;
}) {
  const { t } = useLang();
  const total =
    value.relevance +
      value.authority +
      value.recency +
      value.citation_impact +
      value.evidence || 1;

  const normalized = (k: keyof Weights) => value[k] / total;

  const setRaw = (k: keyof Weights, raw: number) => {
    onChange({ ...value, [k]: raw });
  };

  return (
    <div className={cn("space-y-3", className)}>
      {KEYS.map((k) => {
        const pct = Math.round(normalized(k) * 100);
        return (
          <div key={k}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="flex items-center gap-1 text-[var(--color-fg)]">
                {t(`weights.${k}`)}
                <Tooltip wide label={t(`weights.${k}.desc`)}>
                  <HelpCircle
                    size={12}
                    className="cursor-help text-[var(--color-faint)] hover:text-[var(--color-muted)]"
                  />
                </Tooltip>
              </span>
              <span className="tabular-nums text-[var(--color-accent)]">
                {pct}%
              </span>
            </div>
            <Slider
              min={0}
              max={1}
              step={0.01}
              value={value[k]}
              onChange={(e) => setRaw(k, parseFloat(e.target.value))}
            />
          </div>
        );
      })}
      <p className="pt-1 text-[11px] text-[var(--color-faint)]">
        {t("settings.weightsHint")}
      </p>
    </div>
  );
}
