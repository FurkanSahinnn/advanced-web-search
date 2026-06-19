import { useCallback, useEffect, useRef, useState } from "react";
import { streamUrl } from "./api";
import type {
  ReportGrounding,
  ReportOut,
  ResearchEvent,
  RunQueryOut,
  ScoreBreakdown,
  SourceOut,
  SubtopicOut,
} from "./types";

export type RunStatus =
  | "idle"
  | "connecting"
  | "running"
  | "awaiting_approval"
  | "finished"
  | "error"
  | "cancelled";

export interface RunStreamState {
  events: ResearchEvent[];
  lastByType: Partial<Record<string, ResearchEvent>>;
  status: RunStatus;
  statusMessage: string | null;
  sources: Map<number, SourceOut>;
  subtopics: SubtopicOut[]; // tree
  queries: RunQueryOut[]; // issued search queries (research trail)
  report: ReportOut | null;
  reports: Map<string, ReportOut>; // latest report per language code
  tokens: string; // accumulated synth text
  awaitingApproval: boolean;
  approvalTree: SubtopicOut[];
  activeNode: string | null;
  error: string | null;
  /** Force a reconnect (e.g. after approve resumes the graph). */
  reopen: () => void;
}

// Insert / update a node inside a tree keyed by id (immutably-ish).
function upsertSubtopic(
  tree: SubtopicOut[],
  node: SubtopicOut,
): SubtopicOut[] {
  const flat = new Map<number, SubtopicOut>();
  const collect = (nodes: SubtopicOut[]) => {
    for (const n of nodes) {
      flat.set(n.id, { ...n, children: [] });
      if (n.children?.length) collect(n.children);
    }
  };
  collect(tree);
  // upsert incoming
  const existing = flat.get(node.id);
  flat.set(node.id, {
    ...(existing ?? node),
    ...node,
    children: [],
  });

  // rebuild tree
  const roots: SubtopicOut[] = [];
  const byParent = new Map<number, SubtopicOut[]>();
  for (const n of flat.values()) {
    if (n.parent_id == null || !flat.has(n.parent_id)) {
      roots.push(n);
    } else {
      const arr = byParent.get(n.parent_id) ?? [];
      arr.push(n);
      byParent.set(n.parent_id, arr);
    }
  }
  const attach = (n: SubtopicOut): SubtopicOut => {
    const kids = (byParent.get(n.id) ?? []).sort((a, b) => a.ord - b.ord);
    return { ...n, children: kids.map(attach) };
  };
  return roots.sort((a, b) => a.ord - b.ord).map(attach);
}

export function useRunStream(runId: number | null): RunStreamState {
  const [events, setEvents] = useState<ResearchEvent[]>([]);
  const [lastByType, setLastByType] = useState<
    Partial<Record<string, ResearchEvent>>
  >({});
  const [status, setStatus] = useState<RunStatus>("idle");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [sources, setSources] = useState<Map<number, SourceOut>>(new Map());
  const [subtopics, setSubtopics] = useState<SubtopicOut[]>([]);
  const [queries, setQueries] = useState<RunQueryOut[]>([]);
  const [report, setReport] = useState<ReportOut | null>(null);
  const [reports, setReports] = useState<Map<string, ReportOut>>(new Map());
  const [tokens, setTokens] = useState<string>("");
  const [awaitingApproval, setAwaitingApproval] = useState(false);
  const [approvalTree, setApprovalTree] = useState<SubtopicOut[]>([]);
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reopenKey, setReopenKey] = useState(0);

  const esRef = useRef<EventSource | null>(null);
  // Monotonic negative ids for live query rows (SSE frames carry no DB id),
  // guaranteed unique regardless of event seq so React keys never collide.
  const queryIdRef = useRef(-1);

  const reopen = useCallback(() => {
    // clear awaiting flags so resumed stream starts fresh on the topic
    setAwaitingApproval(false);
    setError(null);
    setReopenKey((k) => k + 1);
  }, []);

  const handleEvent = useCallback((ev: ResearchEvent) => {
    setEvents((prev) => [...prev, ev]);
    setLastByType((prev) => ({ ...prev, [ev.type]: ev }));

    switch (ev.type) {
      case "run_started":
        setStatus("running");
        break;
      case "status": {
        const s = (ev.data?.status as string) ?? null;
        setStatusMessage(s);
        if (s === "running") setStatus("running");
        break;
      }
      case "node_started":
        if (ev.node) setActiveNode(ev.node);
        break;
      case "node_finished":
        setActiveNode((cur) => (cur === ev.node ? null : cur));
        break;
      case "subtopic": {
        const st = ev.data?.subtopic as SubtopicOut | undefined;
        if (st) setSubtopics((prev) => upsertSubtopic(prev, st));
        break;
      }
      case "awaiting_approval": {
        const tree = (ev.data?.subtopics as SubtopicOut[] | undefined) ?? [];
        setApprovalTree(tree);
        if (tree.length) setSubtopics(tree);
        setAwaitingApproval(true);
        setStatus("awaiting_approval");
        setActiveNode("approval");
        break;
      }
      case "source_found": {
        const src = ev.data?.source as SourceOut | undefined;
        if (src) {
          setSources((prev) => {
            const next = new Map(prev);
            next.set(src.id, { ...prev.get(src.id), ...src });
            return next;
          });
        }
        break;
      }
      case "source_scored": {
        const sid = ev.data?.source_id as number | undefined;
        const score = ev.data?.score as ScoreBreakdown | undefined;
        const kept = ev.data?.kept as boolean | undefined;
        if (sid != null) {
          setSources((prev) => {
            const cur = prev.get(sid);
            if (!cur && !score) return prev;
            const next = new Map(prev);
            const merged: SourceOut = {
              ...(cur ?? ({ id: sid } as SourceOut)),
            };
            if (score) {
              merged.score = {
                ...score,
                ...(kept != null ? { kept } : {}),
              };
            }
            next.set(sid, merged);
            return next;
          });
        }
        break;
      }
      case "query": {
        const q = ev.data?.query as string | undefined;
        if (q) {
          const row: RunQueryOut = {
            id: queryIdRef.current--, // unique synthetic id for live rows (no DB id over SSE)
            subtopic_id: (ev.data?.subtopic_id as number | null) ?? null,
            round: (ev.data?.round as number | undefined) ?? 1,
            query: q,
            hits: (ev.data?.hits as number | undefined) ?? 0,
          };
          setQueries((prev) => [...prev, row]);
        }
        break;
      }
      case "token": {
        const t = ev.data?.text as string | undefined;
        if (t) setTokens((prev) => prev + t);
        break;
      }
      case "report": {
        const r = ev.data?.report as ReportOut | undefined;
        if (r) {
          const lang = r.language ?? "en";
          setReports((prev) => {
            const next = new Map(prev);
            next.set(lang, r);
            return next;
          });
          // Only the primary report (ord 0, or legacy reports without ord)
          // drives the headline report + accumulated token view.
          if (r.ord === 0 || r.ord == null) {
            setReport(r);
            setTokens(r.markdown ?? "");
          }
        }
        break;
      }
      case "report_grounding": {
        // Verification ran after the report streamed: patch the grounding-weighted
        // certainty + per-verdict breakdown onto every language's report in place.
        const certainty = ev.data?.certainty as number | undefined;
        const grounding = ev.data?.grounding as ReportGrounding | undefined;
        const patch = (r: ReportOut): ReportOut => ({
          ...r,
          certainty: certainty ?? r.certainty,
          grounding: grounding ?? r.grounding,
        });
        setReports((prev) => {
          const next = new Map(prev);
          for (const [lang, r] of next) next.set(lang, patch(r));
          return next;
        });
        setReport((cur) => (cur ? patch(cur) : cur));
        break;
      }
      case "run_finished": {
        const s = (ev.data?.status as string) ?? "finished";
        setStatus(
          s === "error"
            ? "error"
            : s === "cancelled"
              ? "cancelled"
              : "finished",
        );
        setActiveNode(null);
        break;
      }
      case "error": {
        // Leave null when the frame carries no message so the UI falls back to
        // the localized t("common.error") instead of a hardcoded string.
        const msg = (ev.data?.message as string) ?? ev.message ?? null;
        setError(msg);
        setStatus("error");
        setActiveNode(null);
        break;
      }
      default:
        break;
    }
  }, []);

  useEffect(() => {
    if (runId == null) {
      setStatus("idle");
      return;
    }

    // Reset derived state on a fresh open for this run.
    setStatus("connecting");

    const es = new EventSource(streamUrl(runId));
    esRef.current = es;

    es.onmessage = (e) => {
      if (!e.data) return;
      try {
        const parsed = JSON.parse(e.data) as ResearchEvent;
        handleEvent(parsed);
      } catch {
        // ignore malformed frames / keep-alives
      }
    };

    es.onerror = () => {
      // EventSource auto-reconnects unless the run terminated. If the
      // server closed the stream (terminal), surface idle/finished instead
      // of an error spinner.
      setStatus((cur) =>
        cur === "finished" ||
        cur === "error" ||
        cur === "cancelled" ||
        cur === "awaiting_approval"
          ? cur
          : "connecting",
      );
    };

    return () => {
      es.close();
      esRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, reopenKey, handleEvent]);

  return {
    events,
    lastByType,
    status,
    statusMessage,
    sources,
    subtopics,
    queries,
    report,
    reports,
    tokens,
    awaitingApproval,
    approvalTree,
    activeNode,
    error,
    reopen,
  };
}
