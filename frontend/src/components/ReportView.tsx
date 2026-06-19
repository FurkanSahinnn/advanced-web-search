import { useCallback, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Lightbulb } from "lucide-react";
import type { ReportOut, SourceOut } from "../lib/types";
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

function highlightSource(id: number) {
  const el = document.getElementById(`source-${id}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("citation-flash");
  // force reflow so the animation restarts
  void el.offsetWidth;
  el.classList.add("citation-flash");
}

// Replace inline [n] citation markers with clickable superscripts.
function renderWithCitations(
  text: string,
  sourceByIndex: Map<number, number>,
  onCite: (sourceId: number) => void,
): ReactNode[] {
  const parts: ReactNode[] = [];
  const re = /\[(\d+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const n = parseInt(m[1], 10);
    const sourceId = sourceByIndex.get(n) ?? n;
    parts.push(
      <sup key={`c-${key++}`}>
        <button
          onClick={() => onCite(sourceId)}
          className="mx-0.5 rounded bg-[var(--color-accent-soft)] px-1 text-[10px] font-semibold text-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-[var(--color-accent-fg)]"
          title={`#${n}`}
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
): ReactNode {
  if (typeof children === "string") {
    return renderWithCitations(children, sourceByIndex, onCite);
  }
  if (Array.isArray(children)) {
    return children.map((c, i) =>
      typeof c === "string" ? (
        <span key={i}>
          {renderWithCitations(c, sourceByIndex, onCite)}
        </span>
      ) : (
        c
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
  className,
}: {
  report: ReportOut | null;
  liveMarkdown: string;
  streaming: boolean;
  sources: SourceOut[];
  reports?: ReportOut[];
  activeLang?: string;
  onLangChange?: (lang: string) => void;
  className?: string;
}) {
  const { t } = useLang();

  // Map [n] -> source id. Heuristic: order sources by id; [n] is 1-based index.
  const sourceByIndex = useCallback(() => {
    const ordered = [...sources].sort((a, b) => a.id - b.id);
    const map = new Map<number, number>();
    ordered.forEach((s, i) => map.set(i + 1, s.id));
    return map;
  }, [sources])();

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
    processChildren(children, sourceByIndex, onCite);

  return (
    <div className={cn("flex h-full flex-col overflow-y-auto scrollbar-thin", className)}>
      <div className="mx-auto w-full max-w-3xl px-5 py-5">
        {langTabRow}

        {report?.consensus_summary && (
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
