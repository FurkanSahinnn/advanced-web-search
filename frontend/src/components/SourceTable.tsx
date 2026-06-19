import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ArrowUpDown } from "lucide-react";
import type { ScoreBreakdown, SourceOut } from "../lib/types";
import { useLang } from "../lib/i18n";
import { Badge } from "./ui/badge";
import { Select } from "./ui/select";
import { SourceCard } from "./SourceCard";
import { cn } from "../lib/cn";

type ScoreKey = keyof Pick<
  ScoreBreakdown,
  "relevance" | "authority" | "recency" | "citation_impact" | "evidence"
>;
type SortKey = "title" | ScoreKey | "match_score" | "kept";

const SCORE_COLS: { key: ScoreKey; labelKey: string }[] = [
  { key: "relevance", labelKey: "source.col.relevance" },
  { key: "authority", labelKey: "source.col.authority" },
  { key: "recency", labelKey: "source.col.recency" },
  { key: "citation_impact", labelKey: "source.col.citation" },
  { key: "evidence", labelKey: "source.col.evidence" },
];

function val(s: SourceOut, key: SortKey): number | string {
  if (key === "title") return (s.title ?? s.canonical_id ?? "").toLowerCase();
  if (key === "kept") return s.score?.kept ? 1 : 0;
  if (key === "match_score") return s.score?.match_score ?? 0;
  return s.score?.[key] ?? 0;
}

function Cell({ v }: { v: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, v)) * 100);
  return (
    <td className="px-2 py-2 text-right tabular-nums">
      <span
        className={cn(
          "text-xs",
          pct >= 70
            ? "text-[var(--color-good)]"
            : pct >= 40
              ? "text-[var(--color-fg)]"
              : "text-[var(--color-faint)]",
        )}
      >
        {pct}
      </span>
    </td>
  );
}

const EMPTY_CITED: ReadonlySet<number> = new Set();

export function SourceTable({
  sources,
  citedSourceIds,
  className,
}: {
  sources: SourceOut[];
  // Source ids actually cited in the report (resolved from inline [n] markers).
  // Enables the "cited in report" badge + filter; empty/omitted hides them.
  citedSourceIds?: ReadonlySet<number>;
  className?: string;
}) {
  const { t } = useLang();
  const cited = citedSourceIds ?? EMPTY_CITED;
  const hasCited = cited.size > 0;
  const [keptOnly, setKeptOnly] = useState(false);
  const [citedOnly, setCitedOnly] = useState(false);
  const [kind, setKind] = useState("all");
  const [sort, setSort] = useState<SortKey>("match_score");
  const [asc, setAsc] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  const kinds = useMemo(() => {
    const set = new Set<string>();
    sources.forEach((s) => s.kind && set.add(s.kind));
    return [...set].sort();
  }, [sources]);

  // A stale "cited only" filter must not blank the table once cited info is
  // unavailable (e.g. switching to a report/run without a mapping).
  const citedOnlyActive = citedOnly && hasCited;

  const rows = useMemo(() => {
    let r = sources.slice();
    if (keptOnly) r = r.filter((s) => s.score?.kept);
    if (citedOnlyActive) r = r.filter((s) => cited.has(s.id));
    if (kind !== "all") r = r.filter((s) => s.kind === kind);
    r.sort((a, b) => {
      const va = val(a, sort);
      const vb = val(b, sort);
      let cmp =
        typeof va === "string" && typeof vb === "string"
          ? va.localeCompare(vb)
          : (va as number) - (vb as number);
      return asc ? cmp : -cmp;
    });
    return r;
  }, [sources, keptOnly, citedOnlyActive, cited, kind, sort, asc]);

  const toggleSort = (k: SortKey) => {
    if (sort === k) setAsc((a) => !a);
    else {
      setSort(k);
      setAsc(k === "title");
    }
  };

  if (sources.length === 0) {
    return (
      <div
        className={cn(
          "flex h-full items-center justify-center text-xs text-[var(--color-faint)]",
          className,
        )}
      >
        {t("source.noSources")}
      </div>
    );
  }

  const Th = ({ k, label, num }: { k: SortKey; label: string; num?: boolean }) => (
    <th
      onClick={() => toggleSort(k)}
      className={cn(
        "cursor-pointer select-none whitespace-nowrap px-2 py-2 text-[11px] font-medium uppercase tracking-wide text-[var(--color-muted)] hover:text-[var(--color-fg)]",
        num ? "text-right" : "text-left",
      )}
    >
      <span className="inline-flex items-center gap-1">
        {num && <ArrowUpDown size={11} className={sort === k ? "text-[var(--color-accent)]" : ""} />}
        {label}
        {!num && <ArrowUpDown size={11} className={sort === k ? "text-[var(--color-accent)]" : ""} />}
      </span>
    </th>
  );

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--color-border)] px-3 py-2">
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[var(--color-muted)]">
          <input
            type="checkbox"
            checked={keptOnly}
            onChange={(e) => setKeptOnly(e.target.checked)}
            className="h-4 w-4 accent-[var(--color-accent)]"
          />
          {t("source.keptOnly")}
        </label>
        {hasCited && (
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[var(--color-muted)]">
            <input
              type="checkbox"
              checked={citedOnly}
              onChange={(e) => setCitedOnly(e.target.checked)}
              className="h-4 w-4 accent-[var(--color-accent)]"
            />
            {t("source.citedOnly")}
          </label>
        )}
        <div className="w-40">
          <Select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="h-8 text-xs"
          >
            <option value="all">{t("source.kind.all")}</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </div>
        <span className="ml-auto text-xs text-[var(--color-faint)]">
          {rows.length} / {sources.length}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto scrollbar-thin">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--color-surface)]">
            <tr className="border-b border-[var(--color-border)]">
              <th className="w-6 px-1" />
              <Th k="title" label={t("source.col.title")} />
              {SCORE_COLS.map((c) => (
                <Th key={c.key} k={c.key} label={t(c.labelKey)} num />
              ))}
              <Th k="match_score" label={t("source.col.match")} num />
              <Th k="kept" label={t("source.col.kept")} num />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const open = expanded === s.id;
              const sc = s.score;
              return (
                <Fragment key={s.id}>
                  <tr
                    id={`source-${s.id}`}
                    className="scroll-mt-12 cursor-pointer border-b border-[var(--color-border)] hover:bg-[var(--color-surface-2)]"
                    onClick={() => setExpanded(open ? null : s.id)}
                  >
                    <td className="px-1 text-[var(--color-faint)]">
                      {open ? (
                        <ChevronDown size={14} />
                      ) : (
                        <ChevronRight size={14} />
                      )}
                    </td>
                    <td className="max-w-0 px-2 py-2">
                      <div className="flex items-center gap-1.5">
                        {cited.has(s.id) && (
                          <span
                            title={t("source.citedTip")}
                            className="shrink-0 rounded bg-[var(--color-accent-soft)] px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[var(--color-accent)]"
                          >
                            {t("source.cited")}
                          </span>
                        )}
                        <span className="truncate text-xs text-[var(--color-fg)]">
                          {s.title ?? s.canonical_id}
                        </span>
                      </div>
                      <div className="truncate text-[10px] text-[var(--color-faint)]">
                        {[s.provider, s.kind].filter(Boolean).join(" · ")}
                      </div>
                    </td>
                    {SCORE_COLS.map((c) => (
                      <Cell key={c.key} v={sc?.[c.key] ?? 0} />
                    ))}
                    <td className="px-2 py-2 text-right">
                      <span className="text-xs font-semibold tabular-nums text-[var(--color-fg)]">
                        {sc?.match_score ?? 0}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right">
                      <Badge variant={sc?.kept ? "good" : "default"}>
                        {sc?.kept ? t("source.kept") : t("source.dropped")}
                      </Badge>
                    </td>
                  </tr>
                  {open && (
                    <tr className="bg-[var(--color-bg)]">
                      <td colSpan={9} className="p-2">
                        <SourceCard source={s} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
