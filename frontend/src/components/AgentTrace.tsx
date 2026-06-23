import { useMemo } from "react";
import {
  Brain,
  CheckCircle2,
  CircleDot,
  FileText,
  Gavel,
  ListChecks,
  Search,
  ShieldCheck,
  SortDesc,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ResearchEvent } from "../lib/types";
import { useLang } from "../lib/i18n";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/cn";

const NODE_ORDER = [
  "planner",
  "moderator",
  "approval",
  "researcher",
  "ranker",
  "synthesizer",
  "verifier",
  "finalizer",
] as const;

const NODE_ICON: Record<string, LucideIcon> = {
  planner: Brain,
  moderator: Gavel,
  approval: ListChecks,
  researcher: Search,
  ranker: SortDesc,
  synthesizer: Sparkles,
  verifier: ShieldCheck,
  finalizer: FileText,
};

interface NodeGroup {
  node: string;
  events: ResearchEvent[];
  started: boolean;
  finished: boolean;
  durationMs: number | null;
}

function buildGroups(events: ResearchEvent[]): NodeGroup[] {
  const map = new Map<string, NodeGroup>();
  const startSeq = new Map<string, number>();

  const ensure = (node: string): NodeGroup => {
    let g = map.get(node);
    if (!g) {
      g = { node, events: [], started: false, finished: false, durationMs: null };
      map.set(node, g);
    }
    return g;
  };

  for (const ev of events) {
    const node = ev.node ?? inferNode(ev);
    if (!node) continue;
    const g = ensure(node);
    g.events.push(ev);
    if (ev.type === "node_started") {
      g.started = true;
      startSeq.set(node, ev.seq);
    }
    if (ev.type === "node_finished") {
      g.finished = true;
      const s = startSeq.get(node);
      if (s != null) g.durationMs = (ev.seq - s) * 1; // seq proxy, not wall time
    }
    if (ev.type === "awaiting_approval") g.started = true;
  }

  const known = NODE_ORDER.filter((n) => map.has(n)).map((n) => map.get(n)!);
  const extra = [...map.values()].filter(
    (g) => !NODE_ORDER.includes(g.node as (typeof NODE_ORDER)[number]),
  );
  return [...known, ...extra];
}

function inferNode(ev: ResearchEvent): string | null {
  switch (ev.type) {
    case "plan":
    case "subtopic":
      return "planner";
    case "awaiting_approval":
      return "approval";
    case "source_found":
    case "source_scored":
      return ev.type === "source_scored" ? "ranker" : "researcher";
    case "claim":
    case "citation_verified":
      return "verifier";
    case "token":
    case "report":
      return "synthesizer";
    default:
      return null;
  }
}

export function AgentTrace({
  events,
  activeNode,
  className,
}: {
  events: ResearchEvent[];
  activeNode: string | null;
  className?: string;
}) {
  const { t } = useLang();
  const groups = useMemo(() => buildGroups(events), [events]);

  // Run-level error events carry no node, so they are not grouped above.
  // Surface them explicitly with an error style so they never get swallowed.
  const errorEvents = useMemo(
    () =>
      events.filter(
        (e) =>
          e.type === "error" &&
          (typeof e.message === "string" ||
            typeof e.data?.message === "string"),
      ),
    [events],
  );

  if (groups.length === 0 && errorEvents.length === 0) {
    return (
      <div
        className={cn(
          "flex h-full items-center justify-center px-4 text-center text-xs text-[var(--color-faint)]",
          className,
        )}
      >
        {t("trace.waiting")}
      </div>
    );
  }

  return (
    <ol className={cn("relative space-y-1 px-2 py-2", className)}>
      {groups.map((g) => {
        const Icon = NODE_ICON[g.node] ?? CircleDot;
        const isActive = activeNode === g.node && !g.finished;
        const errored = g.events.some((e) => e.type === "error");
        return (
          <li key={g.node} className="animate-in">
            <div
              className={cn(
                "flex items-start gap-3 rounded-lg px-2 py-2",
                isActive && "bg-[var(--color-surface-2)]",
              )}
            >
              <div
                className={cn(
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
                  errored
                    ? "border-[var(--color-danger)] text-[var(--color-danger)]"
                    : g.finished
                      ? "border-[color-mix(in_srgb,var(--color-accent)_50%,transparent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : isActive
                        ? "border-[var(--color-accent)] text-[var(--color-accent)]"
                        : "border-[var(--color-border-strong)] text-[var(--color-muted)]",
                )}
              >
                {errored ? (
                  <AlertTriangle size={14} />
                ) : g.finished ? (
                  <CheckCircle2 size={15} />
                ) : isActive ? (
                  <Spinner size={14} />
                ) : (
                  <Icon size={14} />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[var(--color-fg)]">
                    {t(`node.${g.node}`)}
                  </span>
                  {isActive && (
                    <span className="text-[10px] uppercase tracking-wide text-[var(--color-accent)]">
                      {t("trace.active")}
                    </span>
                  )}
                </div>
                <NodeDetail group={g} />
              </div>
            </div>
          </li>
        );
      })}

      {errorEvents.map((e, i) => {
        const msg =
          (e.data?.message as string) ?? e.message ?? t("run.error");
        return (
          <li key={`error-${e.seq ?? i}`} className="animate-in">
            <div className="flex items-start gap-3 rounded-lg border border-[color-mix(in_srgb,var(--color-danger)_40%,transparent)] bg-[color-mix(in_srgb,var(--color-danger)_10%,transparent)] px-2 py-2">
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--color-danger)] text-[var(--color-danger)]">
                <AlertTriangle size={14} />
              </div>
              <div className="min-w-0 flex-1">
                <span className="text-sm font-medium text-[var(--color-danger)]">
                  {t("run.error")}
                </span>
                <p
                  className="mt-0.5 break-words text-[11px] text-[var(--color-danger)]"
                  title={msg}
                >
                  {msg}
                </p>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function NodeDetail({ group }: { group: NodeGroup }) {
  const { t } = useLang();
  const counts = useMemo(() => {
    const c = {
      subtopic: 0,
      source_found: 0,
      source_scored: 0,
      kept: 0,
      claim: 0,
      verified: 0,
      tokens: 0,
    };
    for (const e of group.events) {
      if (e.type === "subtopic") c.subtopic++;
      if (e.type === "source_found") c.source_found++;
      if (e.type === "source_scored") {
        c.source_scored++;
        if (e.data?.kept) c.kept++;
      }
      if (e.type === "claim") c.claim++;
      if (e.type === "citation_verified" && e.data?.verified) c.verified++;
      if (e.type === "token") c.tokens++;
    }
    return c;
  }, [group.events]);

  const lastMsg = useMemo(() => {
    for (let i = group.events.length - 1; i >= 0; i--) {
      const m = group.events[i].message ?? (group.events[i].data?.message as string);
      if (m) return m;
    }
    return null;
  }, [group.events]);

  // A ranker `log` frame carries data.degraded when the cross-encoder reranker
  // fell back to identity mode and the relevance ranking collapsed to source
  // order — surface it so the quality drop isn't silent.
  const degraded = useMemo(
    () =>
      group.events.some(
        (e) => e.type === "log" && Boolean((e.data as Record<string, unknown>)?.degraded),
      ),
    [group.events],
  );

  const chips: string[] = [];
  if (counts.subtopic)
    chips.push(`${counts.subtopic} ${t("trace.chip.subtopic")}`);
  if (counts.source_found)
    chips.push(`${counts.source_found} ${t("trace.chip.source")}`);
  if (counts.source_scored)
    chips.push(`${counts.kept}/${counts.source_scored} ${t("trace.chip.kept")}`);
  if (counts.claim) chips.push(`${counts.claim} ${t("trace.chip.claim")}`);
  if (counts.verified) chips.push(`${counts.verified} ${t("trace.chip.verified")}`);
  if (counts.tokens) chips.push(`${counts.tokens} ${t("trace.chip.token")}`);

  return (
    <div className="mt-0.5 space-y-1">
      {(chips.length > 0 || degraded) && (
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-[var(--color-muted)]">
          {chips.map((c, i) => (
            <span key={i}>{c}</span>
          ))}
          {degraded && (
            <span
              className="inline-flex items-center gap-1 text-[var(--color-warn)]"
              title={t("quality.degraded")}
            >
              <AlertTriangle size={11} /> {t("trace.chip.degraded")}
            </span>
          )}
        </div>
      )}
      {lastMsg && (
        <p className="truncate text-[11px] text-[var(--color-faint)]" title={lastMsg}>
          {lastMsg}
        </p>
      )}
    </div>
  );
}
