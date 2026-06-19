import { Fragment, useCallback, useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Lightbulb, Scale } from "lucide-react";
import type { CitationVerdict, ReportOut, SourceOut } from "../lib/types";
import { useLang } from "../lib/i18n";
import { langKey } from "../lib/languages";
import { Progress } from "./ui/progress";
import { cn } from "../lib/cn";

// LLMs emit math with TeX delimiters `\[ … \]` (display) and `\( … \)` (inline)
// that markdown renders literally. remark-math only understands `$…$` / `$$…$$`,
// so normalize the TeX delimiters into dollar form before parsing. Code spans
// and fenced blocks (including a still-open fence/span while the report is
// streaming) are left untouched so literal backslash-parens in code survive.
function normalizeMath(src: string): string {
  if (!src) return src;
  // Capture code regions so they pass through verbatim: a closed fence/span,
  // OR an unterminated trailing fence/span (the latter matters while streaming,
  // before the closing delimiter has arrived). Any captured segment begins with
  // a backtick, which is how we tell code from prose below.
  const parts = src.split(/(```[\s\S]*?```|```[\s\S]*$|`[^`\n]+`|`[^`\n]*$)/g);
  return parts
    .map((seg) => {
      if (!seg || seg.startsWith("`")) return seg; // code — leave literal
      return (
        seg
          // Escape bare currency dollars ($5, $10) so remark-math's single-$
          // inline rule doesn't pair two of them and italicize the prose
          // between. Run this BEFORE introducing our own `$` math below so it
          // only ever touches original dollar signs, never the math we emit.
          .replace(/\$(?=\d)/g, "\\$")
          .replace(/\\\[([\s\S]+?)\\\]/g, (_, x) => `\n\n$$\n${x.trim()}\n$$\n\n`)
          .replace(/\\\(([\s\S]+?)\\\)/g, (_, x) => `$${x.trim()}$`)
      );
    })
    .join("");
}

export function highlightSource(id: number) {
  const el = document.getElementById(`source-${id}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("citation-flash");
  // force reflow so the animation restarts
  void el.offsetWidth;
  el.classList.add("citation-flash");
}

// Inline [n] badge tint by verification verdict (when known). No verdict keeps
// the neutral accent style so unverified runs look exactly as before.
const VERDICT_STYLE: Record<CitationVerdict, { color: string; bg: string }> = {
  supported: {
    color: "var(--color-good)",
    bg: "color-mix(in srgb, var(--color-good) 18%, transparent)",
  },
  partial: {
    color: "var(--color-warn)",
    bg: "color-mix(in srgb, var(--color-warn) 18%, transparent)",
  },
  unsupported: {
    color: "var(--color-danger)",
    bg: "color-mix(in srgb, var(--color-danger) 18%, transparent)",
  },
  unverifiable: {
    color: "var(--color-faint)",
    bg: "color-mix(in srgb, var(--color-faint) 16%, transparent)",
  },
};

// Replace inline [n] citation markers with clickable superscripts. When a
// per-source verification verdict is known, the marker is tinted accordingly
// and its tooltip names the verdict. Exported so Ask-the-Report answers render
// citations identically to the report body.
export function renderWithCitations(
  text: string,
  sourceByIndex: Map<number, number>,
  onCite: (sourceId: number) => void,
  verdicts: ReadonlyMap<number, CitationVerdict> | undefined,
  t: (k: string) => string,
): ReactNode[] {
  const parts: ReactNode[] = [];
  const re = /\[(\d+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const n = parseInt(m[1], 10);
    // Resolve to the exact source; if the marker has no mapping (e.g. a bracketed
    // number that isn't a real citation, or an old report whose heuristic falls
    // short), the click is a no-op rather than scrolling to an arbitrary row.
    const sourceId = sourceByIndex.get(n);
    const verdict = sourceId != null ? verdicts?.get(sourceId) : undefined;
    const vs = verdict ? VERDICT_STYLE[verdict] : null;
    parts.push(
      <sup key={`c-${key++}`}>
        <button
          onClick={() => sourceId != null && onCite(sourceId)}
          className={cn(
            "mx-0.5 rounded px-1 text-[10px] font-semibold",
            vs
              ? "hover:brightness-110"
              : "bg-[var(--color-accent-soft)] text-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-[var(--color-accent-fg)]",
          )}
          style={vs ? { color: vs.color, background: vs.bg } : undefined}
          title={verdict ? `#${n} · ${t(`verify.${verdict}`)}` : `#${n}`}
        >
          {n}
        </button>
      </sup>,
    );
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function processChildren(
  children: ReactNode,
  sourceByIndex: Map<number, number>,
  onCite: (id: number) => void,
  verdicts: ReadonlyMap<number, CitationVerdict> | undefined,
  t: (k: string) => string,
): ReactNode {
  if (typeof children === "string") {
    return renderWithCitations(children, sourceByIndex, onCite, verdicts, t);
  }
  if (Array.isArray(children)) {
    return children.map((c, i) =>
      typeof c === "string" ? (
        <span key={i}>
          {renderWithCitations(c, sourceByIndex, onCite, verdicts, t)}
        </span>
      ) : (
        <Fragment key={i}>{c}</Fragment>
      ),
    );
  }
  return children;
}

function Meter({ label, value }: { label: string; value: number | null }) {
  if (value == null) return null;
  const pct = value <= 1 ? value * 100 : value;
  return (
    <div className="flex-1">
      <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--color-muted)]">
        <span>{label}</span>
        <span className="tabular-nums text-[var(--color-fg)]">
          {Math.round(pct)}%
        </span>
      </div>
      <Progress value={pct} />
    </div>
  );
}

export function ReportView({
  report,
  liveMarkdown,
  streaming,
  sources,
  reports,
  activeLang,
  onLangChange,
  verdicts,
  className,
}: {
  report: ReportOut | null;
  liveMarkdown: string;
  streaming: boolean;
  sources: SourceOut[];
  reports?: ReportOut[];
  activeLang?: string;
  onLangChange?: (lang: string) => void;
  // Per-source citation verdicts; tints the inline [n] markers when present.
  verdicts?: ReadonlyMap<number, CitationVerdict>;
  className?: string;
}) {
  const { t } = useLang();

  // Map [n] -> source id. Prefer the report's persisted [n]->source mapping
  // (`references`, where index i holds the source for marker [i+1]) so a marker
  // resolves to the EXACT source. Older runs without it fall back to the legacy
  // heuristic: order sources by id and treat [n] as the 1-based index.
  const refs = report?.references;
  const sourceByIndex = useMemo(() => {
    const map = new Map<number, number>();
    if (refs && refs.length > 0) {
      refs.forEach((sid, i) => map.set(i + 1, sid));
      return map;
    }
    const ordered = [...sources].sort((a, b) => a.id - b.id);
    ordered.forEach((s, i) => map.set(i + 1, s.id));
    return map;
  }, [sources, refs]);

  const onCite = useCallback((id: number) => highlightSource(id), []);

  const rawMd = report?.markdown ?? liveMarkdown;
  const md = normalizeMath(rawMd);

  // Language tab row: only shown once more than one language was generated.
  // The parent owns which report is displayed; clicking a tab calls back up.
  const langTabs = reports ?? [];
  const showLangTabs = langTabs.length > 1;
  const currentLang = activeLang ?? report?.language;
  const langTabRow = showLangTabs ? (
    <div className="mb-4 flex flex-wrap gap-1.5">
      {langTabs.map((r) => (
        <button
          key={r.language}
          type="button"
          onClick={() => onLangChange?.(r.language)}
          aria-pressed={r.language === currentLang}
          className={cn(
            "rounded-[var(--radius)] border px-2.5 py-1.5 text-xs font-medium transition-colors",
            r.language === currentLang
              ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
              : "border-[var(--color-border)] bg-[var(--color-surface-2)] text-[var(--color-muted)] hover:border-[var(--color-border-strong)] hover:text-[var(--color-fg)]",
          )}
        >
          {t(langKey(r.language))}
        </button>
      ))}
    </div>
  ) : null;

  if (!rawMd) {
    return (
      <div
        className={cn(
          "flex h-full flex-col overflow-y-auto scrollbar-thin",
          className,
        )}
      >
        {showLangTabs && (
          <div className="mx-auto w-full max-w-3xl px-5 pt-5">{langTabRow}</div>
        )}
        <div className="flex flex-1 items-center justify-center px-4 text-center text-sm text-[var(--color-faint)]">
          {streaming ? t("research.streaming") : t("research.noReport")}
        </div>
      </div>
    );
  }

  const proc = (children: ReactNode) =>
    processChildren(children, sourceByIndex, onCite, verdicts, t);

  return (
    <div className={cn("flex h-full flex-col overflow-y-auto scrollbar-thin", className)}>
      <div className="mx-auto w-full max-w-3xl px-5 py-5">
        {langTabRow}

        {report?.consensus_summary?.trim() && (
          <div className="mb-4 flex gap-2.5 rounded-lg border border-[color-mix(in_srgb,var(--color-accent)_35%,transparent)] bg-[var(--color-accent-soft)] p-3">
            <Lightbulb
              size={18}
              className="mt-0.5 shrink-0 text-[var(--color-accent)]"
            />
            <div>
              <p className="text-xs font-semibold text-[var(--color-accent)]">
                {t("report.consensus")}
              </p>
              <p className="mt-0.5 text-sm text-[var(--color-fg)]">
                {report.consensus_summary}
              </p>
            </div>
          </div>
        )}

        {report?.disagreements?.trim() && (
          <div className="mb-4 flex gap-2.5 rounded-lg border border-[color-mix(in_srgb,var(--color-danger)_30%,transparent)] bg-[color-mix(in_srgb,var(--color-danger)_8%,transparent)] p-3">
            <Scale
              size={18}
              className="mt-0.5 shrink-0 text-[var(--color-danger)]"
            />
            <div>
              <p className="text-xs font-semibold text-[var(--color-danger)]">
                {t("report.disagreements")}
              </p>
              <p className="mt-0.5 text-sm text-[var(--color-fg)]">
                {report.disagreements}
              </p>
            </div>
          </div>
        )}

        {(report?.comprehensiveness != null ||
          report?.certainty != null) && (
          <div className="mb-5 flex gap-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
            <Meter
              label={t("report.comprehensiveness")}
              value={report?.comprehensiveness ?? null}
            />
            <Meter
              label={t("report.certainty")}
              value={report?.certainty ?? null}
            />
          </div>
        )}

        {report?.grounding && report.grounding.graded > 0 && (
          <div className="-mt-3 mb-5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--color-muted)]">
            <span className="font-medium text-[var(--color-fg)]">
              {t("report.grounding")}:
            </span>
            <span className="tabular-nums">
              {report.grounding.grounded}/{report.grounding.graded}{" "}
              {t("report.grounded")}
            </span>
            {(
              ["supported", "partial", "unsupported", "unverifiable"] as CitationVerdict[]
            ).map((v) =>
              report.grounding![v] > 0 ? (
                <span key={v} className="inline-flex items-center gap-1">
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ background: VERDICT_STYLE[v].color }}
                  />
                  <span className="tabular-nums">{report.grounding![v]}</span>{" "}
                  {t(`verify.${v}`)}
                </span>
              ) : null,
            )}
          </div>
        )}

        {verdicts && verdicts.size > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-[10px] text-[var(--color-muted)]">
            <span className="font-medium text-[var(--color-fg)]">
              {t("verify.legend")}:
            </span>
            {(
              ["supported", "partial", "unsupported", "unverifiable"] as CitationVerdict[]
            ).map((v) => (
              <span key={v} className="inline-flex items-center gap-1">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: VERDICT_STYLE[v].color }}
                />
                {t(`verify.${v}`)}
              </span>
            ))}
          </div>
        )}

        <article
          className={cn(
            "report-prose text-[var(--color-fg)]",
            streaming && !report && "stream-caret",
          )}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}
            components={{
              h1: ({ children }) => (
                <h1 className="mb-3 mt-5 text-2xl font-bold tracking-tight">
                  {proc(children)}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 className="mb-2 mt-5 border-b border-[var(--color-border)] pb-1 text-xl font-semibold">
                  {proc(children)}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="mb-2 mt-4 text-lg font-semibold">
                  {proc(children)}
                </h3>
              ),
              p: ({ children }) => (
                <p className="my-3 leading-relaxed text-[var(--color-fg)]">
                  {proc(children)}
                </p>
              ),
              li: ({ children }) => (
                <li className="my-1 ml-1 leading-relaxed">{proc(children)}</li>
              ),
              ul: ({ children }) => (
                <ul className="my-3 list-disc space-y-1 pl-5">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="my-3 list-decimal space-y-1 pl-5">{children}</ol>
              ),
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-[var(--color-accent)] underline decoration-dotted underline-offset-2 hover:decoration-solid"
                >
                  {children}
                </a>
              ),
              blockquote: ({ children }) => (
                <blockquote className="my-3 border-l-2 border-[var(--color-accent)] pl-3 italic text-[var(--color-muted)]">
                  {children}
                </blockquote>
              ),
              code: ({ children, className: cls }) =>
                cls ? (
                  <code className={cls}>{children}</code>
                ) : (
                  <code className="rounded bg-[var(--color-surface-2)] px-1 py-0.5 text-[0.85em] text-[var(--color-accent)]">
                    {children}
                  </code>
                ),
              pre: ({ children }) => (
                <pre className="my-3 overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3 text-xs">
                  {children}
                </pre>
              ),
              table: ({ children }) => (
                <div className="my-3 overflow-x-auto">
                  <table className="w-full border-collapse text-sm">
                    {children}
                  </table>
                </div>
              ),
              th: ({ children }) => (
                <th className="border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1 text-left text-xs font-semibold">
                  {proc(children)}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-[var(--color-border)] px-2 py-1 text-sm">
                  {proc(children)}
                </td>
              ),
              hr: () => <hr className="my-5 border-[var(--color-border)]" />,
            }}
          >
            {md}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  );
}
