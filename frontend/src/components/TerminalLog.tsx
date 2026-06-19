import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ArrowDown, Copy, Check, Trash2 } from "lucide-react";
import type { ResearchEvent } from "../lib/types";
import type { RunStatus } from "../lib/sse";
import { useLang } from "../lib/i18n";
import { cn } from "../lib/cn";

/** Cap on lines kept in the DOM. Older lines are dropped (counter shown). */
const MAX_LINES = 2000;

interface TermLine {
  key: number;
  ts: string; // HH:MM:SS
  tag: string;
  text: string;
  colorClass: string;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function stampNow(): string {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Map a single ResearchEvent -> a terminal line descriptor (tag + colorClass).
 * Returns null for events that should not be rendered (e.g. raw tokens).
 */
function formatEvent(
  ev: ResearchEvent,
  firstTokenSeen: boolean,
): { tag: string; text: string; colorClass: string } | null {
  const msg =
    (typeof ev.message === "string" && ev.message) ||
    (typeof ev.data?.message === "string" ? (ev.data.message as string) : "");

  switch (ev.type) {
    case "node_started":
      return {
        tag: ev.node ?? "node",
        text: msg || "started",
        colorClass: "text-cyan-300 font-semibold",
      };
    case "node_finished":
      return {
        tag: ev.node ?? "node",
        text: msg || "done",
        colorClass: "text-cyan-400 font-semibold",
      };
    case "run_started":
      return { tag: "run", text: "run started", colorClass: "text-cyan-300 font-semibold" };
    case "plan":
    case "subtopic": {
      const st = ev.data?.subtopic as { question?: string } | undefined;
      const text = msg || st?.question || ev.type;
      return { tag: ev.type, text, colorClass: "text-blue-300" };
    }
    case "awaiting_approval":
      return {
        tag: "approval",
        text: msg || "awaiting plan approval",
        colorClass: "text-blue-300",
      };
    case "source_found": {
      const src = ev.data?.source as
        | { provider?: string; title?: string }
        | undefined;
      const text =
        msg ||
        (src
          ? `+ ${src.provider ?? "?"}: ${src.title ?? "(untitled)"}`
          : "source found");
      return { tag: "source", text, colorClass: "text-emerald-400" };
    }
    case "source_scored": {
      const kept = ev.data?.kept as boolean | undefined;
      const sid = ev.data?.source_id;
      const text = msg || `scored #${sid ?? "?"}${kept ? " (kept)" : " (dropped)"}`;
      return { tag: "score", text, colorClass: "text-zinc-500" };
    }
    case "claim":
      return { tag: "claim", text: msg || "claim", colorClass: "text-fuchsia-400" };
    case "citation_verified": {
      const verified = ev.data?.verified as boolean | undefined;
      const dead = ev.data?.dead_link as boolean | undefined;
      const text =
        msg ||
        `citation source #${ev.data?.source_id ?? "?"} -> ${
          verified ? "ok" : dead ? "dead" : "?"
        }`;
      return {
        tag: "cite",
        text,
        colorClass: verified ? "text-fuchsia-400" : "text-red-400",
      };
    }
    case "report":
      return {
        tag: "report",
        text: msg || "report ready",
        colorClass: "text-green-400 font-semibold",
      };
    case "run_finished": {
      const s = (ev.data?.status as string) ?? "finished";
      return {
        tag: "run",
        text: msg || `run ${s}`,
        colorClass:
          s === "error"
            ? "text-red-400 font-bold"
            : "text-green-400 font-semibold",
      };
    }
    case "error":
      return {
        tag: "error",
        text: msg || "error",
        colorClass: "text-red-400 font-bold",
      };
    case "token":
      // Never render per token: surface a single "writing report" line on the
      // very first token, then skip the rest.
      if (firstTokenSeen) return null;
      return {
        tag: "synth",
        text: "writing report…",
        colorClass: "text-zinc-400",
      };
    case "log": {
      const m = msg || "";
      const trimmed = m.trim();
      // Request-style lines: GET / verify / fulltext / snowball.
      if (/^(GET|verify|fulltext|snowball)\b/.test(trimmed)) {
        let colorClass = "text-teal-300"; // request (teal) default
        if (/\b(dead|failed|skip\/failed)\b/i.test(m)) colorClass = "text-red-400";
        else if (/\bskip\b/i.test(m)) colorClass = "text-amber-400";
        return { tag: "req", text: m, colorClass };
      }
      // Result continuation lines from the researcher (indented).
      if (/^\s+(ok\b|skip\/failed\b|\+)/.test(m)) {
        let colorClass = "text-teal-300";
        if (/skip\/failed/i.test(m)) colorClass = "text-amber-400";
        else if (/^\s+\+/.test(m)) colorClass = "text-emerald-400";
        return { tag: "req", text: m, colorClass };
      }
      return { tag: ev.node ?? "log", text: m, colorClass: "text-zinc-400" };
    }
    default:
      return null;
  }
}

export function TerminalLog({
  events,
  status,
  className,
}: {
  events: ResearchEvent[];
  status: RunStatus;
  className?: string;
}) {
  const { t } = useLang();

  // Local "cleared" baseline: events before this index are hidden locally.
  const [clearedCount, setClearedCount] = useState(0);
  const [autoScroll, setAutoScroll] = useState(true);
  const [atBottom, setAtBottom] = useState(true);
  const [copied, setCopied] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Stable arrival timestamps keyed by event index (events only ever append).
  const tsRef = useRef<string[]>([]);

  // Fold events -> lines. Timestamps are stamped at arrival order (events lack
  // a real ts), memoized so they stay stable as the array grows.
  const allLines = useMemo<TermLine[]>(() => {
    const out: TermLine[] = [];
    let tokenSeen = false;
    for (let i = 0; i < events.length; i++) {
      const ev = events[i];
      if (tsRef.current[i] == null) tsRef.current[i] = stampNow();

      const isToken = ev.type === "token";
      const firstTokenSeen = isToken && tokenSeen;
      const desc = formatEvent(ev, firstTokenSeen);
      if (isToken) tokenSeen = true;
      if (!desc) continue;

      out.push({
        key: i,
        ts: tsRef.current[i],
        tag: desc.tag,
        text: desc.text,
        colorClass: desc.colorClass,
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length]);

  // Apply the local "clear" baseline + cap to the last MAX_LINES.
  const visibleAll = useMemo(
    () => allLines.filter((l) => l.key >= clearedCount),
    [allLines, clearedCount],
  );
  const hiddenCount = Math.max(0, visibleAll.length - MAX_LINES);
  const lines = hiddenCount > 0 ? visibleAll.slice(-MAX_LINES) : visibleAll;

  const isLive = status === "running" || status === "awaiting_approval";

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAtBottom(nearBottom);
    // Scrolling up pauses auto-scroll; returning to bottom resumes it.
    if (!nearBottom && autoScroll) setAutoScroll(false);
    if (nearBottom && !autoScroll) setAutoScroll(true);
  }, [autoScroll]);

  useLayoutEffect(() => {
    if (!autoScroll) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length, autoScroll]);

  const jumpToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setAutoScroll(true);
    setAtBottom(true);
  }, []);

  const clear = useCallback(() => {
    setClearedCount(allLines.length ? allLines[allLines.length - 1].key + 1 : 0);
  }, [allLines]);

  const copyAll = useCallback(() => {
    const text = visibleAll
      .map((l) => `${l.ts} [${l.tag}] ${l.text}`)
      .join("\n");
    try {
      void navigator.clipboard?.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  }, [visibleAll]);

  return (
    <div
      className={cn(
        "flex min-h-0 flex-col overflow-hidden bg-[#0a0b0e] font-mono text-[12px] leading-relaxed text-zinc-300",
        className,
      )}
    >
      {/* Fake terminal header bar */}
      <div className="flex shrink-0 items-center gap-2 border-b border-white/10 bg-[#15171c] px-3 py-1.5">
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-[#ff5f56]" />
          <span className="h-3 w-3 rounded-full bg-[#ffbd2e]" />
          <span className="h-3 w-3 rounded-full bg-[#27c93f]" />
        </span>
        <span className="ml-1 truncate text-[11px] text-zinc-400">
          {t("terminal.title")}
        </span>
        {isLive && (
          <span className="ml-1 inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
        )}

        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => setAutoScroll((v) => !v)}
            title={t("terminal.autoscroll")}
            className={cn(
              "rounded px-2 py-0.5 text-[10px] uppercase tracking-wide transition-colors",
              autoScroll
                ? "bg-emerald-500/20 text-emerald-300"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            {t("terminal.autoscroll")}
          </button>
          <button
            type="button"
            onClick={copyAll}
            title={t("terminal.copy")}
            className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-zinc-200"
          >
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </button>
          <button
            type="button"
            onClick={clear}
            title={t("terminal.clear")}
            className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-zinc-200"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Log body */}
      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="terminal-scanlines h-full overflow-y-auto px-3 py-2 scrollbar-thin"
        >
          {hiddenCount > 0 && (
            <div className="mb-1 select-none text-[11px] italic text-zinc-600">
              … {hiddenCount} {t("terminal.earlierLines")}
            </div>
          )}
          {lines.length === 0 ? (
            <div className="select-none text-zinc-600">
              <span className="text-emerald-400">$</span> {t("trace.waiting")}
            </div>
          ) : (
            lines.map((l, idx) => {
              const isLast = idx === lines.length - 1;
              return (
                <div
                  key={l.key}
                  className="flex gap-2 whitespace-pre-wrap break-words"
                >
                  <span className="shrink-0 select-none text-zinc-600">
                    {l.ts}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 select-none text-zinc-500",
                    )}
                  >
                    [{l.tag}]
                  </span>
                  <span className={cn("min-w-0", l.colorClass)}>
                    {l.text}
                    {isLast && isLive && (
                      <span className="ml-0.5 inline-block animate-pulse text-emerald-300">
                        ▋
                      </span>
                    )}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Jump-to-bottom affordance (only when scrolled up) */}
        {!atBottom && (
          <button
            type="button"
            onClick={jumpToBottom}
            className="absolute bottom-3 right-4 flex items-center gap-1 rounded-full border border-white/15 bg-[#15171c] px-3 py-1 text-[11px] text-zinc-200 shadow-lg hover:bg-[#1d2026]"
          >
            <ArrowDown size={12} /> {t("terminal.jumpToBottom")}
          </button>
        )}
      </div>
    </div>
  );
}
