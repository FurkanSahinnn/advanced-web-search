import { useState } from "react";
import { Check, Copy, ExternalLink, Quote } from "lucide-react";
import type { ScoreBreakdown, SourceOut } from "../lib/types";
import { api } from "../lib/api";
import { useLang } from "../lib/i18n";
import { Badge } from "./ui/badge";
import { cn } from "../lib/cn";

function CopyCiteButton({ sourceId }: { sourceId: number }) {
  const { t } = useLang();
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    try {
      const text = await api.citeSource(sourceId, "bibtex");
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore copy failures */
    }
  };

  return (
    <button
      type="button"
      onClick={onCopy}
      title={t("source.copyCite")}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none transition-colors",
        copied
          ? "border-[color-mix(in_srgb,var(--color-good)_45%,transparent)] bg-[color-mix(in_srgb,var(--color-good)_15%,transparent)] text-[var(--color-good)]"
          : "border-[var(--color-border-strong)] text-[var(--color-muted)] hover:text-[var(--color-accent)]",
      )}
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {copied ? t("common.copied") : t("source.copyCite")}
    </button>
  );
}

function ScoreRing({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  const color =
    pct >= 75
      ? "var(--color-good)"
      : pct >= 50
        ? "var(--color-accent)"
        : pct >= 30
          ? "var(--color-warn)"
          : "var(--color-danger)";
  return (
    <div
      className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full"
      style={{
        background: `conic-gradient(${color} ${pct * 3.6}deg, var(--color-border-strong) 0deg)`,
      }}
    >
      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--color-surface)] text-xs font-semibold text-[var(--color-fg)]">
        {Math.round(pct)}
      </div>
    </div>
  );
}

const CRITERIA: {
  key: keyof Pick<
    ScoreBreakdown,
    "relevance" | "authority" | "recency" | "citation_impact" | "evidence"
  >;
  labelKey: string;
}[] = [
  { key: "relevance", labelKey: "source.col.relevance" },
  { key: "authority", labelKey: "source.col.authority" },
  { key: "recency", labelKey: "source.col.recency" },
  { key: "citation_impact", labelKey: "source.col.citation" },
  { key: "evidence", labelKey: "source.col.evidence" },
];

function MiniBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-[10px] text-[var(--color-muted)]">
        {label}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--color-border-strong)]">
        <div
          className="h-full rounded-full bg-[var(--color-accent)]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-7 shrink-0 text-right text-[10px] tabular-nums text-[var(--color-faint)]">
        {Math.round(pct)}
      </span>
    </div>
  );
}

export function SourceCard({
  source,
  className,
}: {
  source: SourceOut;
  className?: string;
}) {
  const { t } = useLang();
  const sc = source.score;
  const match = sc?.match_score ?? 0;
  const meta = [source.provider, source.kind, source.venue, source.published_date]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <ScoreRing value={match} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            {source.url ? (
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer noopener"
                className="group flex items-start gap-1 text-sm font-medium text-[var(--color-fg)] hover:text-[var(--color-accent)]"
              >
                <span className="line-clamp-2">
                  {source.title ?? source.canonical_id}
                </span>
                <ExternalLink
                  size={13}
                  className="mt-0.5 shrink-0 text-[var(--color-faint)] group-hover:text-[var(--color-accent)]"
                />
              </a>
            ) : (
              <span className="line-clamp-2 text-sm font-medium text-[var(--color-fg)]">
                {source.title ?? source.canonical_id}
              </span>
            )}
          </div>

          {meta && (
            <p className="mt-0.5 truncate text-[11px] text-[var(--color-muted)]">
              {meta}
            </p>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {sc && (
              <Badge variant={sc.kept ? "good" : "default"}>
                {sc.kept ? t("source.kept") : t("source.dropped")}
              </Badge>
            )}
            {sc?.evidence_type && sc.evidence_type !== "unknown" && (
              <Badge variant="info">{sc.evidence_type.replace(/_/g, " ")}</Badge>
            )}
            {source.is_oa && <Badge variant="accent">{t("source.oa")}</Badge>}
            {source.cited_by_count != null && source.cited_by_count > 0 && (
              <Badge variant="outline">
                {source.cited_by_count} {t("source.citedBy")}
              </Badge>
            )}
            <CopyCiteButton sourceId={source.id} />
          </div>
        </div>
      </div>

      {sc && (
        <div className="mt-3 space-y-1">
          {CRITERIA.map((c) => (
            <MiniBar key={c.key} label={t(c.labelKey)} value={sc[c.key]} />
          ))}
        </div>
      )}

      {sc?.why_kept && (
        <div className="mt-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1.5 text-[11px] text-[var(--color-muted)]">
          <span className="font-medium text-[var(--color-fg)]">
            {t("source.whyKept")}:
          </span>{" "}
          {sc.why_kept}
        </div>
      )}

      {sc?.supporting_quote && (
        <blockquote className="mt-2 flex gap-1.5 border-l-2 border-[var(--color-accent)] pl-2 text-[11px] italic text-[var(--color-muted)]">
          <Quote size={12} className="mt-0.5 shrink-0 text-[var(--color-accent)]" />
          <span className="line-clamp-3">{sc.supporting_quote}</span>
        </blockquote>
      )}
    </div>
  );
}
