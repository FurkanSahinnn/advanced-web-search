import { useMemo, useState } from "react";
import { Plus, Trash2, GripVertical } from "lucide-react";
import type { ApprovalDecision, SubtopicEdit, SubtopicOut } from "../lib/types";
import { useLang } from "../lib/i18n";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/cn";

interface Row extends SubtopicEdit {
  depth: number;
}

function flatten(tree: SubtopicOut[]): Row[] {
  const out: Row[] = [];
  const walk = (nodes: SubtopicOut[]) => {
    for (const n of [...nodes].sort((a, b) => a.ord - b.ord)) {
      out.push({
        id: n.id,
        parent_id: n.parent_id,
        question: n.question,
        perspective: n.perspective ?? null,
        keep: true,
        depth: n.depth,
      });
      if (n.children?.length) walk(n.children);
    }
  };
  walk(tree);
  return out;
}

export function ApprovalPanel({
  tree,
  onApprove,
  className,
}: {
  tree: SubtopicOut[];
  onApprove: (decision: ApprovalDecision) => Promise<void> | void;
  className?: string;
}) {
  const { t } = useLang();
  const initial = useMemo(() => flatten(tree), [tree]);
  const [rows, setRows] = useState<Row[]>(initial);
  const [extra, setExtra] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [nextId, setNextId] = useState(-1);

  const update = (id: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const remove = (id: number) =>
    setRows((rs) => rs.filter((r) => r.id !== id && r.parent_id !== id));

  const addRow = () => {
    const id = nextId;
    setNextId((n) => n - 1);
    setRows((rs) => [
      ...rs,
      { id, parent_id: null, question: "", perspective: null, keep: true, depth: 0 },
    ]);
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      const approved_subtopics: SubtopicEdit[] = rows
        .filter((r) => r.question.trim().length > 0)
        .map(({ id, parent_id, question, perspective, keep }) => ({
          id,
          parent_id,
          question: question.trim(),
          perspective: perspective?.trim() ? perspective.trim() : null,
          keep,
        }));
      await onApprove({
        approved_subtopics,
        extra_instructions: extra.trim() || undefined,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const keptCount = rows.filter((r) => r.keep && r.question.trim()).length;

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className="border-b border-[var(--color-border)] px-4 py-3">
        <h2 className="text-sm font-semibold text-[var(--color-fg)]">
          {t("approval.title")}
        </h2>
        <p className="mt-0.5 text-xs text-[var(--color-muted)]">
          {t("approval.hint")}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3 scrollbar-thin">
        {rows.map((r) => (
          <div
            key={r.id}
            className={cn(
              "rounded-lg border bg-[var(--color-surface)] p-2.5 transition-opacity",
              r.keep
                ? "border-[var(--color-border)]"
                : "border-[var(--color-border)] opacity-55",
            )}
            style={{ marginLeft: r.depth * 16 }}
          >
            <div className="flex items-start gap-2">
              <GripVertical
                size={16}
                className="mt-2 shrink-0 text-[var(--color-faint)]"
              />
              <div className="flex-1 space-y-2">
                <Input
                  value={r.question}
                  placeholder={t("approval.question")}
                  onChange={(e) => update(r.id, { question: e.target.value })}
                  className={r.id < 0 ? "border-[var(--color-accent)]" : undefined}
                />
                <div className="flex items-center gap-2">
                  <Input
                    value={r.perspective ?? ""}
                    placeholder={t("approval.perspectivePlaceholder")}
                    onChange={(e) =>
                      update(r.id, { perspective: e.target.value })
                    }
                    className="h-8 flex-1 text-xs"
                  />
                  <label className="flex cursor-pointer items-center gap-1.5 whitespace-nowrap text-xs text-[var(--color-muted)]">
                    <input
                      type="checkbox"
                      checked={r.keep}
                      onChange={(e) => update(r.id, { keep: e.target.checked })}
                      className="h-4 w-4 accent-[var(--color-accent)]"
                    />
                    {t("approval.keep")}
                  </label>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => remove(r.id)}
                    aria-label="remove"
                    className="h-8 w-8 text-[var(--color-faint)] hover:text-[var(--color-danger)]"
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        ))}

        <Button variant="secondary" size="sm" onClick={addRow} className="mt-1">
          <Plus size={15} /> {t("approval.add")}
        </Button>

        <div className="pt-2">
          <label className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
            {t("approval.extra")}
          </label>
          <Textarea
            rows={3}
            value={extra}
            placeholder={t("approval.extraPlaceholder")}
            onChange={(e) => setExtra(e.target.value)}
          />
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-[var(--color-border)] px-4 py-3">
        <span className="text-xs text-[var(--color-muted)]">{keptCount} ✓</span>
        <Button onClick={submit} disabled={submitting || keptCount === 0}>
          {submitting && <Spinner size={15} className="text-current" />}
          {submitting ? t("approval.submitting") : t("approval.submit")}
        </Button>
      </div>
    </div>
  );
}
