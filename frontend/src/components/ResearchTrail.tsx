import { useMemo, useState } from "react";
import { Search, ChevronRight, ChevronDown } from "lucide-react";
import type { RunQueryOut, SourceOut, SubtopicOut } from "../lib/types";
import { useLang } from "../lib/i18n";
import { cn } from "../lib/cn";

function flatten(nodes: SubtopicOut[], out: SubtopicOut[] = []): SubtopicOut[] {
  for (const n of nodes) {
    out.push(n);
    if (n.children?.length) flatten(n.children, out);
  }
  return out;
}

interface Group {
  key: number | null;
  label: string;
  perspective: string | null;
  queries: RunQueryOut[];
  sources: SourceOut[];
}

/**
 * Research trail: the actual search process behind a report — which queries
 * were issued per sub-question (and round), how many hits each returned, and
 * which sources were kept / dropped / cited. Reconstructed from persisted
 * queries+sources, so it works for reopened runs; updates live during a run.
 */
export function ResearchTrail({
  queries,
  subtopics,
  sources,
  citedSourceIds,
  className,
}: {
  queries: RunQueryOut[];
  subtopics: SubtopicOut[];
  sources: SourceOut[];
  citedSourceIds: ReadonlySet<number>;
  className?: string;
}) {
  const { t } = useLang();
  const [openDrops, setOpenDrops] = useState<Set<string>>(new Set());

  const groups = useMemo<Group[]>(() => {
    const flat = flatten(subtopics);
    const byId = new Map<number, SubtopicOut>();
    for (const s of flat) byId.set(s.id, s);

    const qBy = new Map<number | null, RunQueryOut[]>();
    for (const q of queries) {
      const k = q.subtopic_id ?? null;
      (qBy.get(k) ?? qBy.set(k, []).get(k)!).push(q);
    }
    const sBy = new Map<number | null, SourceOut[]>();
    for (const s of sources) {
      const k = s.subtopic_id ?? null;
      (sBy.get(k) ?? sBy.set(k, []).get(k)!).push(s);
    }

    const keys = new Set<number | null>();
    queries.forEach((q) => keys.add(q.subtopic_id ?? null));
    sources.forEach((s) => keys.add(s.subtopic_id ?? null));

    const make = (k: number | null): Group => ({
      key: k,
      label:
        k == null
          ? t("trail.other")
          : byId.get(k)?.question ?? `#${k}`,
      perspective: k == null ? null : byId.get(k)?.perspective ?? null,
      queries: qBy.get(k) ?? [],
      sources: sBy.get(k) ?? [],
    });

    const out: Group[] = [];
    const used = new Set<number | null>();
    for (const s of flat) {
      if (!keys.has(s.id)) continue;
      used.add(s.id);
      out.push(make(s.id));
    }
    for (const k of keys) {
      if (used.has(k)) continue;
      out.push(make(k));
    }
    return out;
  }, [queries, subtopics, sources, t]);

  const hasAny = groups.some((g) => g.queries.length || g.sources.length);
  if (!hasAny) {
    return (
      <div
        className={cn(
          "flex h-full items-center justify-center px-4 text-center text-xs text-[var(--color-faint)]",
          className,
        )}
      >
        {t("trail.empty")}
      </div>
    );
  }

  return (
    <div className={cn("h-full overflow-y-auto scrollbar-thin px-4 py-3", className)}>
      <div className="mx-auto w-full max-w-3xl space-y-4">
        {groups.map((g) => {
          const kept = g.sources.filter((s) => s.score?.kept).length;
          const cited = g.sources.filter((s) => citedSourceIds.has(s.id)).length;
          const dropped = g.sources.filter((s) => s.score && !s.score.kept);
          // Prefix so the null catch-all bucket can never collide with an
          // integer subtopic id once stringified.
          const dropKey = g.key == null ? "g-null" : `g-${g.key}`;
          const dropOpen = openDrops.has(dropKey);
          return (
            <div
              key={dropKey}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
            >
              <div className="flex items-start gap-2">
                <Search size={14} className="mt-0.5 shrink-0 text-[var(--color-accent)]" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-[var(--color-fg)]">
                    {g.label}
                  </p>
                  {g.perspective && (
                    <p className="text-[11px] italic text-[var(--color-faint)]">
                      {g.perspective}
                    </p>
                  )}
                </div>
              </div>

              {g.queries.length > 0 && (
                <div className="mt-2 space-y-1">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
                    {t("trail.queries")}
                  </p>
                  {g.queries.map((q) => (
                    <div
                      key={`${q.id}-${q.round}-${q.query.slice(0, 24)}`}
                      className="flex items-center gap-2 text-[11px] text-[var(--color-fg)]"
                    >
                      <span className="shrink-0 rounded bg-[var(--color-surface-2)] px-1 py-0.5 text-[9px] font-semibold text-[var(--color-muted)]">
                        {t("trail.round")}{q.round}
                      </span>
                      <span className="min-w-0 flex-1 truncate" title={q.query}>
                        {q.query}
                      </span>
                      <span className="shrink-0 tabular-nums text-[var(--color-faint)]">
                        {q.hits} {t("trail.hits")}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {g.sources.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-[var(--color-muted)]">
                  <span>{g.sources.length} {t("trail.found")}</span>
                  <span className="text-[var(--color-good)]">{kept} {t("trail.kept")}</span>
                  {cited > 0 && (
                    <span className="text-[var(--color-accent)]">
                      {cited} {t("source.citedShort")}
                    </span>
                  )}
                  {dropped.length > 0 && (
                    <button
                      type="button"
                      aria-expanded={dropOpen}
                      onClick={() =>
                        setOpenDrops((prev) => {
                          const next = new Set(prev);
                          if (next.has(dropKey)) next.delete(dropKey);
                          else next.add(dropKey);
                          return next;
                        })
                      }
                      className="inline-flex items-center gap-0.5 text-[var(--color-faint)] hover:text-[var(--color-fg)]"
                    >
                      {dropOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      {dropped.length} {t("trail.dropped")}
                    </button>
                  )}
                </div>
              )}

              {dropOpen && dropped.length > 0 && (
                <div className="mt-1.5 space-y-1 border-t border-[var(--color-border)] pt-1.5">
                  {dropped.map((s) => (
                    <div key={s.id} className="text-[11px] text-[var(--color-muted)]">
                      <span className="text-[var(--color-fg)]">
                        {s.title ?? s.canonical_id}
                      </span>
                      {s.score && (
                        <span className="text-[var(--color-faint)]">
                          {" "}
                          — {s.score.match_score}
                          {s.score.why_kept ? ` · ${s.score.why_kept}` : ""}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
