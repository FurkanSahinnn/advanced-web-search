import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, X, Terminal, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "../lib/api";
import { useRunStream } from "../lib/sse";
import type { RunStatus } from "../lib/sse";
import { useLang } from "../lib/i18n";
import type {
  ApprovalDecision,
  ProjectDetail,
  ReportOut,
  ResearchEvent,
  SourceOut,
} from "../lib/types";
import { AgentTrace } from "../components/AgentTrace";
import { TerminalLog } from "../components/TerminalLog";
import { NoModelBanner } from "../components/NoModelBanner";
import { ExportMenu } from "../components/ExportMenu";
import { TopicGraph } from "../components/TopicGraph";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { ReportView } from "../components/ReportView";
import { SourceTable } from "../components/SourceTable";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/ui/button";
import { Spinner } from "../components/ui/spinner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { ResizeHandle } from "../components/ui/ResizeHandle";
import { useResizable } from "../lib/useResizable";
import { reconstructTrace } from "../lib/reconstructTrace";

export function Research() {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useLang();
  const nav = useNavigate();

  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState(false);
  // Which report language is shown. `null` = follow the primary (first) report.
  const [activeLang, setActiveLang] = useState<string | null>(null);
  // Live console bottom dock. `null` = user hasn't toggled; follow run activity.
  const [consoleOpen, setConsoleOpen] = useState<boolean | null>(null);

  // Resizable panel sizes (px), persisted to localStorage. Drag the dividers
  // between panels (or the bar above the console) to resize; double-click a
  // divider to restore its default.
  const left = useResizable({ key: "aws.panel.left", initial: 300, min: 200, max: 560 });
  const right = useResizable({ key: "aws.panel.right", initial: 440, min: 280, max: 820 });
  const consoleH = useResizable({ key: "aws.console.height", initial: 280, min: 120, max: 720 });

  useEffect(() => {
    let active = true;
    if (!projectId) return;
    api
      .getProject(projectId)
      .then((d) => {
        if (!active) return;
        setDetail(d);
        setRunId(d.latest_run?.id ?? null);
      })
      .catch(() => active && setLoadError(t("research.notFound")));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const stream = useRunStream(runId);

  // Clear the local "cancelling" flag once the run actually reports cancelled.
  useEffect(() => {
    if (stream.status === "cancelled") setCancelling(false);
  }, [stream.status]);

  // Merge persisted sources (from initial load) with live-streamed ones.
  const mergedSources = useMemo<SourceOut[]>(() => {
    const map = new Map<number, SourceOut>();
    for (const s of detail?.sources ?? []) map.set(s.id, s);
    for (const [id, s] of stream.sources) map.set(id, { ...map.get(id), ...s });
    return [...map.values()];
  }, [detail?.sources, stream.sources]);

  const subtopics =
    stream.subtopics.length > 0 ? stream.subtopics : (detail?.subtopics ?? []);

  // Per-language reports: start from the persisted set (initial load) and
  // overlay anything streamed live (newest wins). Older runs with a single
  // language land in here too, keyed by their `language`. `allReports` is
  // primary-first (ord 0 = primary).
  const reportsByLang = useMemo<Map<string, ReportOut>>(() => {
    const map = new Map<string, ReportOut>();
    for (const r of detail?.reports ?? []) map.set(r.language, r);
    for (const [lang, r] of stream.reports) map.set(lang, r);
    return map;
  }, [detail?.reports, stream.reports]);

  const allReports = useMemo<ReportOut[]>(
    () =>
      [...reportsByLang.values()].sort((a, b) => (a.ord ?? 0) - (b.ord ?? 0)),
    [reportsByLang],
  );

  // The language actually rendered: the user's pick if any, else the primary.
  const effectiveLang = activeLang ?? allReports[0]?.language;
  // Fall back to the live stream / persisted single report so backward-compatible
  // runs (NULL report_languages) keep showing exactly as before.
  const selectedReport =
    (effectiveLang ? reportsByLang.get(effectiveLang) : undefined) ??
    stream.report ??
    detail?.report ??
    null;
  const report = selectedReport;
  const rootQuery = detail?.project.root_query ?? "";
  const title = detail?.project.title || rootQuery;

  const effectiveStatus =
    stream.status === "idle"
      ? (detail?.latest_run?.status ?? detail?.project.status ?? "idle")
      : stream.status;

  const isStreaming =
    stream.status === "running" || stream.status === "connecting";
  const hasReport = !!report || stream.tokens.length > 0;

  // Reopening a finished project loses the live SSE trace (the per-node events
  // are never persisted), so rebuild an equivalent completed trace from the
  // run's stored artifacts. Used whenever the live stream carries no node
  // frames — i.e. a reopened finished run, whose stream only re-emits
  // `run_finished`. During a live run the node frames win as they arrive.
  const reconstructedTrace = useMemo(
    () =>
      reconstructTrace({
        runId: runId ?? 0,
        status: effectiveStatus,
        subtopics,
        sources: mergedSources,
        claims: detail?.claims ?? [],
        hasReport: !!report,
        error: detail?.latest_run?.error ?? null,
      }),
    [
      runId,
      effectiveStatus,
      subtopics,
      mergedSources,
      detail?.claims,
      report,
      detail?.latest_run?.error,
    ],
  );
  // The live stream carries a real trace once any node frame (or a run-level
  // error) has arrived; a reopened finished run only re-emits a node-less
  // `run_finished`, so it falls through to the reconstruction.
  const liveHasTrace = stream.events.some(
    (e) => e.node != null || e.type === "error",
  );
  const traceEvents = liveHasTrace ? stream.events : reconstructedTrace;

  // The run is "active" (and therefore cancellable) while it is streaming or
  // parked at the approval interrupt.
  const isActive =
    isStreaming ||
    stream.status === "awaiting_approval" ||
    effectiveStatus === "running" ||
    effectiveStatus === "awaiting_approval";
  const isCancelled =
    stream.status === "cancelled" || effectiveStatus === "cancelled";

  // Resolve the console's open state (user toggle wins; else follow activity).
  const consoleIsOpen = consoleOpen ?? isActive;

  const onApprove = async (decision: ApprovalDecision) => {
    if (runId == null) return;
    await api.approve(runId, decision);
    // Resuming: re-open the SSE stream to continue the graph.
    stream.reopen();
  };

  const onCancel = async () => {
    if (runId == null || cancelling) return;
    setCancelling(true);
    try {
      await api.cancel(runId);
    } catch {
      /* best-effort; the run status will still reflect the attempt */
    }
  };

  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20">
        <p className="text-sm text-[var(--color-muted)]">{loadError}</p>
        <Button variant="secondary" onClick={() => nav("/")}>
          <ArrowLeft size={15} /> {t("research.back")}
        </Button>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size={22} />
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[var(--color-border)] px-4 py-2.5">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => nav("/")}
          aria-label={t("research.back")}
        >
          <ArrowLeft size={17} />
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold text-[var(--color-fg)]">
            {title}
          </h1>
          <p className="truncate text-[11px] text-[var(--color-faint)]">
            {rootQuery}
          </p>
        </div>
        {isStreaming && <Spinner size={15} />}
        <StatusBadge status={effectiveStatus} />
        <ExportMenu
          runId={runId}
          disabled={!hasReport && mergedSources.length === 0}
          languages={allReports.map((r) => r.language)}
          activeLang={effectiveLang}
        />
        {isActive && !isCancelled && (
          <Button
            variant="danger"
            size="sm"
            onClick={onCancel}
            disabled={cancelling}
          >
            <X size={14} />{" "}
            {cancelling ? t("run.cancelling") : t("run.cancel")}
          </Button>
        )}
      </div>

      <NoModelBanner />

      {(stream.error || effectiveStatus === "error") && (
        <div className="border-b border-[var(--color-danger)] bg-[color-mix(in_srgb,var(--color-danger)_12%,transparent)] px-4 py-2 text-xs text-[var(--color-danger)]">
          <span className="font-semibold">{t("run.error")}:</span>{" "}
          {stream.error ?? detail?.latest_run?.error ?? t("common.error")}
        </div>
      )}

      {/* 3-region layout — resizable columns (drag the dividers) */}
      <div
        className="flex min-h-0 flex-1 flex-col lg:flex-row"
        style={
          {
            "--left-w": `${left.size}px`,
            "--right-w": `${right.size}px`,
          } as CSSProperties
        }
      >
        {/* Left: AgentTrace */}
        <aside className="hidden min-h-0 shrink-0 flex-col overflow-y-auto border-r border-[var(--color-border)] bg-[var(--color-surface)] scrollbar-thin lg:flex lg:w-[var(--left-w)]">
          <div className="border-b border-[var(--color-border)] px-3 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted)]">
            {t("research.trace")}
          </div>
          <AgentTrace events={traceEvents} activeNode={stream.activeNode} />
        </aside>

        <ResizeHandle
          axis="x"
          sign={1}
          value={left.size}
          onChange={left.set}
          onReset={left.reset}
          min={left.min}
          max={left.max}
          className="hidden lg:block"
          aria-label={t("research.trace")}
        />

        {/* Center: Approval | Graph -> Report */}
        <section className="flex min-h-0 min-w-0 flex-1 flex-col lg:border-r lg:border-[var(--color-border)]">
          {stream.awaitingApproval ? (
            <ApprovalPanel
              tree={
                stream.approvalTree.length ? stream.approvalTree : subtopics
              }
              onApprove={onApprove}
            />
          ) : (
            <Tabs
              defaultValue={hasReport ? "report" : "graph"}
              className="flex min-h-0 flex-1 flex-col"
            >
              <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-3 py-2">
                <TabsList>
                  <TabsTrigger value="graph">{t("research.graph")}</TabsTrigger>
                  <TabsTrigger value="report">
                    {t("research.report")}
                  </TabsTrigger>
                </TabsList>
                {isStreaming && hasReport && (
                  <span className="text-[11px] text-[var(--color-accent)]">
                    {t("research.streaming")}
                  </span>
                )}
              </div>
              <TabsContent
                value="graph"
                className="min-h-0 flex-1 [&>div]:h-full"
              >
                <div className="h-full">
                  <TopicGraph rootQuery={rootQuery} subtopics={subtopics} />
                </div>
              </TabsContent>
              <TabsContent value="report" className="min-h-0 flex-1">
                <ReportView
                  report={selectedReport}
                  reports={allReports}
                  activeLang={effectiveLang}
                  onLangChange={setActiveLang}
                  liveMarkdown={stream.tokens}
                  streaming={isStreaming}
                  sources={mergedSources}
                />
              </TabsContent>
            </Tabs>
          )}
        </section>

        <ResizeHandle
          axis="x"
          sign={-1}
          value={right.size}
          onChange={right.set}
          onReset={right.reset}
          min={right.min}
          max={right.max}
          className="hidden lg:block"
          aria-label={t("research.sources")}
        />

        {/* Right: SourceTable */}
        <aside
          className="flex min-h-0 shrink-0 flex-col border-t border-[var(--color-border)] max-lg:h-[45vh] lg:w-[var(--right-w)] lg:border-t-0"
          id="sources-pane"
        >
          <div className="border-b border-[var(--color-border)] px-3 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted)]">
            {t("research.sources")}{" "}
            <span className="text-[var(--color-faint)]">
              ({mergedSources.length})
            </span>
          </div>
          <SourceTable sources={mergedSources} />
        </aside>
      </div>

      {/* Bottom dock: live debug terminal (IDE/Coolify style) — resizable */}
      {consoleIsOpen && (
        <ResizeHandle
          axis="y"
          sign={-1}
          value={consoleH.size}
          onChange={consoleH.set}
          onReset={consoleH.reset}
          min={consoleH.min}
          max={consoleH.max}
          aria-label={t("research.console")}
        />
      )}
      <ConsoleDock
        open={consoleIsOpen}
        onToggle={() => setConsoleOpen((cur) => !(cur ?? isActive))}
        events={stream.events}
        status={stream.status}
        live={isActive}
        height={consoleH.size}
      />
    </div>
  );
}

function ConsoleDock({
  open,
  onToggle,
  events,
  status,
  live,
  height,
}: {
  open: boolean;
  onToggle: () => void;
  events: ResearchEvent[];
  status: RunStatus;
  live: boolean;
  height: number;
}) {
  const { t } = useLang();
  return (
    <div className="shrink-0 border-t border-[var(--color-border)] bg-[#0a0b0e]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-zinc-300 hover:bg-white/5"
      >
        <Terminal size={14} className="text-emerald-400" />
        <span>{t("research.console")}</span>
        {live && (
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
        )}
        <span className="ml-auto text-zinc-500">
          {open ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
        </span>
      </button>
      {open && (
        <div style={{ height }} className="border-t border-white/10">
          <TerminalLog events={events} status={status} className="h-full" />
        </div>
      )}
    </div>
  );
}
