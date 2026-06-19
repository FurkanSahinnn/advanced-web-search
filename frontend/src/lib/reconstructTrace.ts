import type {
  ClaimOut,
  ResearchEvent,
  SourceOut,
  SubtopicOut,
} from "./types";

// Run statuses that mean the graph reached its END node.
const DONE_STATUSES = new Set(["done", "finished", "completed"]);

function flattenSubtopics(tree: SubtopicOut[]): SubtopicOut[] {
  const out: SubtopicOut[] = [];
  const walk = (nodes: SubtopicOut[]) => {
    for (const n of nodes) {
      out.push(n);
      if (n.children?.length) walk(n.children);
    }
  };
  walk(tree);
  return out;
}

/**
 * Rebuild a finished run's agent-trace from its PERSISTED artifacts.
 *
 * The live per-node events are ephemeral — nodes `emit()` them only onto the
 * SSE stream while the run is in flight; they are never stored. So a reopened
 * completed project has no live trace and the left panel would otherwise sit on
 * "waiting for events" forever. The DB still holds the run's products
 * (sub-questions, sources + their scores, claims, the report), which is enough
 * to reconstruct an equivalent COMPLETED trace: each node that demonstrably ran
 * is emitted as started→finished with the same summary chips the live trace
 * shows. Returns [] when there is nothing to reconstruct (a brand-new run).
 *
 * Order doesn't matter — AgentTrace re-sorts groups by its own NODE_ORDER.
 */
export function reconstructTrace(args: {
  runId: number;
  status: string;
  subtopics: SubtopicOut[];
  sources: SourceOut[];
  claims: ClaimOut[];
  hasReport: boolean;
  error?: string | null;
}): ResearchEvent[] {
  const { runId, status, subtopics, sources, claims, hasReport, error } = args;
  const flatSubs = flattenSubtopics(subtopics);
  const scored = sources.filter((s) => s.score != null);

  const events: ResearchEvent[] = [];
  let seq = 0;
  const push = (
    type: ResearchEvent["type"],
    node: string | null,
    data: Record<string, unknown> = {},
  ) => {
    events.push({ type, run_id: runId, seq: seq++, node, data });
  };
  // Wrap a node's detail frames in started/finished so it renders as completed.
  const node = (name: string, detail: () => void) => {
    push("node_started", name);
    detail();
    push("node_finished", name);
  };

  // planner — produced the sub-question tree.
  if (flatSubs.length) {
    node("planner", () => {
      for (let i = 0; i < flatSubs.length; i++) push("subtopic", "planner");
    });
    // moderator — runs whenever planning happened (it refines the questions).
    node("moderator", () => {});
  }

  // researcher — gathered the sources.
  if (sources.length) {
    node("researcher", () => {
      for (let i = 0; i < sources.length; i++) push("source_found", "researcher");
    });
  }

  // ranker — scored the sources and decided which to keep.
  if (scored.length) {
    node("ranker", () => {
      for (const s of scored)
        push("source_scored", "ranker", { kept: !!s.score?.kept });
    });
  }

  // synthesizer — wrote the report.
  if (hasReport) {
    node("synthesizer", () => {});
  }

  // verifier — extracted claims and verified their citations.
  if (claims.length) {
    node("verifier", () => {
      for (let i = 0; i < claims.length; i++) push("claim", "verifier");
      for (const c of claims)
        for (const cit of c.citations ?? [])
          if (cit.verified)
            push("citation_verified", "verifier", { verified: true });
    });
  }

  // finalizer — only when the run actually reached a done state.
  if (DONE_STATUSES.has(status) && (hasReport || sources.length > 0)) {
    node("finalizer", () => {});
  }

  // Surface a run-level error so it is never silently dropped on reopen.
  if (error && status === "error") {
    push("error", null, { message: error });
  }

  return events;
}
