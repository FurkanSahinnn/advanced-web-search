import { useMemo, useState, type FormEvent } from "react";
import { Sparkles, CornerDownLeft } from "lucide-react";
import type { AskAnswer, CitationVerdict, SourceOut } from "../lib/types";
import { api } from "../lib/api";
import { useLang } from "../lib/i18n";
import { renderWithCitations, highlightSource } from "./ReportView";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/cn";

/**
 * Ask-the-Report: a grounded follow-up Q&A docked under the report. Each answer
 * is produced by the backend ONLY from this run's gathered sources and carries
 * the same clickable [n] citations as the report. Ungrounded answers (nothing
 * relevant in the run's sources) are flagged rather than silently guessed.
 */
export function AskReport({
  runId,
  sources,
  verdicts,
  initial,
  language,
}: {
  runId: number | null;
  sources: SourceOut[];
  verdicts?: ReadonlyMap<number, CitationVerdict>;
  initial?: AskAnswer[];
  language?: string;
}) {
  const { t } = useLang();
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [asked, setAsked] = useState<AskAnswer[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Persisted history (reopened run) first, then anything asked this session.
  const items = useMemo(
    () => [...(initial ?? []), ...asked],
    [initial, asked],
  );

  const sourceIds = useMemo(() => new Set(sources.map((s) => s.id)), [sources]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || runId == null || loading) return;
    setLoading(true);
    setError(null);
    try {
      const ans = await api.askReport(runId, q, language);
      setAsked((prev) => [...prev, ans]);
      setQuestion("");
    } catch {
      setError(t("ask.error"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex shrink-0 flex-col border-t border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
        <Sparkles size={13} className="text-[var(--color-accent)]" />
        {t("ask.title")}
      </div>

      {items.length > 0 && (
        <div className="max-h-[34vh] overflow-y-auto px-3 pb-2 scrollbar-thin">
          {items.map((a) => (
            <AskItem
              key={a.id}
              ans={a}
              sourceIds={sourceIds}
              verdicts={verdicts}
            />
          ))}
        </div>
      )}

      <form onSubmit={submit} className="flex items-center gap-2 px-3 py-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t("ask.placeholder")}
          disabled={loading || runId == null}
          className="min-w-0 flex-1 rounded-[var(--radius)] border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-1.5 text-sm text-[var(--color-fg)] placeholder:text-[var(--color-faint)] focus:border-[var(--color-accent)] focus:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={loading || !question.trim() || runId == null}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius)] bg-[var(--color-accent)] px-3 py-1.5 text-sm font-medium text-[var(--color-accent-fg)] transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {loading ? <Spinner size={14} /> : <CornerDownLeft size={14} />}
          {t("ask.send")}
        </button>
      </form>

      {error && (
        <p className="px-3 pb-2 text-[11px] text-[var(--color-danger)]">{error}</p>
      )}
    </div>
  );
}

function AskItem({
  ans,
  sourceIds,
  verdicts,
}: {
  ans: AskAnswer;
  sourceIds: Set<number>;
  verdicts?: ReadonlyMap<number, CitationVerdict>;
}) {
  const { t } = useLang();
  // [n] -> source id, from the answer's own dense reference list (index+1 == n).
  const sourceByIndex = useMemo(() => {
    const m = new Map<number, number>();
    (ans.references ?? []).forEach((sid, i) => {
      if (sourceIds.has(sid)) m.set(i + 1, sid);
    });
    return m;
  }, [ans.references, sourceIds]);

  return (
    <div className="mt-2 border-t border-[var(--color-border)] pt-2 first:mt-0 first:border-t-0 first:pt-0">
      <p className="text-xs font-semibold text-[var(--color-fg)]">{ans.question}</p>
      {ans.answer ? (
        <p
          className={cn(
            "mt-1 text-sm leading-relaxed text-[var(--color-fg)]",
            !ans.grounded && "text-[var(--color-muted)]",
          )}
        >
          {renderWithCitations(ans.answer, sourceByIndex, highlightSource, verdicts, t)}
        </p>
      ) : (
        <p className="mt-1 text-sm italic text-[var(--color-faint)]">
          {t("ask.notFound")}
        </p>
      )}
      {!ans.grounded && ans.answer && (
        <p className="mt-0.5 text-[10px] text-[var(--color-faint)]">
          {t("ask.ungrounded")}
        </p>
      )}
    </div>
  );
}
