import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ShieldCheck,
  Clock,
  Award,
  Trash2,
  Sparkles,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useLang } from "../lib/i18n";
import { REPORT_LANGUAGE_CODES, langKey } from "../lib/languages";
import type { ProjectOut, SearchDepth } from "../lib/types";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Card } from "../components/ui/card";
import { Spinner } from "../components/ui/spinner";
import { StatusBadge } from "../components/StatusBadge";
import { NoModelBanner } from "../components/NoModelBanner";
import { cn } from "../lib/cn";

const DEPTHS: SearchDepth[] = ["quick", "standard", "deep", "exhaustive"];

export function Home() {
  const { t } = useLang();
  const nav = useNavigate();

  const [query, setQuery] = useState("");
  const [reportLanguages, setReportLanguages] = useState<string[]>(["auto"]);
  const [depth, setDepth] = useState<SearchDepth>("quick");
  const [requireApproval, setRequireApproval] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [projects, setProjects] = useState<ProjectOut[] | null>(null);

  const loadProjects = async () => {
    try {
      setProjects(await api.listProjects());
    } catch {
      setProjects([]);
    }
  };

  useEffect(() => {
    loadProjects();
  }, []);

  const toggleLanguage = (code: string) => {
    setReportLanguages((prev) => {
      if (code === "auto") return ["auto"];
      const withoutAuto = prev.filter((c) => c !== "auto");
      const next = withoutAuto.includes(code)
        ? withoutAuto.filter((c) => c !== code)
        : [...withoutAuto, code];
      return next.length === 0 ? ["auto"] : next;
    });
  };

  const submit = async () => {
    const q = query.trim();
    if (q.length < 3 || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { project } = await api.createProject(q, {
        report_languages: reportLanguages,
        language: reportLanguages.includes("auto")
          ? "auto"
          : reportLanguages[0],
        depth,
        require_approval: requireApproval,
      });
      nav(`/research/${project.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("common.error"));
      setSubmitting(false);
    }
  };

  const onDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    await api.deleteProject(id).catch(() => {});
    loadProjects();
  };

  const values = [
    { icon: ShieldCheck, title: t("home.value1"), desc: t("home.value1d") },
    { icon: Clock, title: t("home.value2"), desc: t("home.value2d") },
    { icon: Award, title: t("home.value3"), desc: t("home.value3d") },
  ];

  return (
    <>
      <NoModelBanner />
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-6 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--color-accent)] text-[var(--color-accent-fg)]">
          <Sparkles size={24} />
        </div>
        <h1 className="text-balance text-3xl font-bold tracking-tight text-[var(--color-fg)] sm:text-4xl">
          {t("home.heroTitle")}
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-balance text-sm text-[var(--color-muted)]">
          {t("home.heroSub")}
        </p>
      </div>

      <Card className="p-4">
        <label className="mb-1.5 block text-xs font-medium text-[var(--color-muted)]">
          {t("home.queryLabel")}
        </label>
        <Textarea
          autoFocus
          rows={4}
          value={query}
          placeholder={t("home.queryPlaceholder")}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
          }}
          className="text-base"
        />

        <div className="mt-3">
          <label className="mb-1.5 block text-[11px] text-[var(--color-faint)]">
            {t("home.depth")}
          </label>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            {DEPTHS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDepth(d)}
                aria-pressed={depth === d}
                className={cn(
                  "rounded-[var(--radius)] border px-2.5 py-1.5 text-xs font-medium transition-colors",
                  depth === d
                    ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                    : "border-[var(--color-border)] bg-[var(--color-surface-2)] text-[var(--color-muted)] hover:border-[var(--color-border-strong)] hover:text-[var(--color-fg)]",
                )}
              >
                {t(`depth.${d}`)}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] leading-snug text-[var(--color-muted)]">
            {t(`depth.${depth}.desc`)}
          </p>
        </div>

        <div className="mt-3">
          <label className="mb-1.5 block text-[11px] text-[var(--color-faint)]">
            {t("home.reportLanguage")}
          </label>
          <div className="flex flex-wrap gap-1.5">
            {REPORT_LANGUAGE_CODES.map((code) => {
              const active = reportLanguages.includes(code);
              return (
                <button
                  key={code}
                  type="button"
                  onClick={() => toggleLanguage(code)}
                  aria-pressed={active}
                  className={cn(
                    "rounded-[var(--radius)] border px-2.5 py-1.5 text-xs font-medium transition-colors",
                    active
                      ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : "border-[var(--color-border)] bg-[var(--color-surface-2)] text-[var(--color-muted)] hover:border-[var(--color-border-strong)] hover:text-[var(--color-fg)]",
                  )}
                >
                  {t(langKey(code))}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[11px] leading-snug text-[var(--color-muted)]">
            {t("home.reportLanguageHint")}
          </p>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-[var(--color-muted)]">
            <input
              type="checkbox"
              checked={requireApproval}
              onChange={(e) => setRequireApproval(e.target.checked)}
              className="h-4 w-4 accent-[var(--color-accent)]"
            />
            <span title={t("home.requireApprovalHint")}>
              {t("home.requireApproval")}
            </span>
          </label>

          <Button
            onClick={submit}
            disabled={submitting || query.trim().length < 3}
            size="lg"
            className="ml-auto"
          >
            {submitting ? (
              <Spinner size={16} className="text-current" />
            ) : (
              <ArrowRight size={16} />
            )}
            {submitting ? t("home.submitting") : t("home.submit")}
          </Button>
        </div>

        {error && (
          <p className="mt-2 text-xs text-[var(--color-danger)]">{error}</p>
        )}
      </Card>

      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {values.map((v) => (
          <div
            key={v.title}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
          >
            <v.icon size={18} className="mb-2 text-[var(--color-accent)]" />
            <p className="text-sm font-medium text-[var(--color-fg)]">
              {v.title}
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-muted)]">{v.desc}</p>
          </div>
        ))}
      </div>

      <section className="mt-9">
        <h2 className="mb-3 text-sm font-semibold text-[var(--color-fg)]">
          {t("home.recent")}
        </h2>
        {projects === null ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : projects.length === 0 ? (
          <p className="rounded-lg border border-dashed border-[var(--color-border)] px-4 py-8 text-center text-xs text-[var(--color-faint)]">
            {t("home.noProjects")}
          </p>
        ) : (
          <ul className="space-y-2">
            {projects.map((p) => (
              <li
                key={p.id}
                onClick={() => nav(`/research/${p.id}`)}
                className={cn(
                  "group flex cursor-pointer items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2.5 transition-colors hover:border-[var(--color-border-strong)] hover:bg-[var(--color-surface-2)]",
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[var(--color-fg)]">
                    {p.title || p.root_query}
                  </p>
                  <p className="truncate text-[11px] text-[var(--color-faint)]">
                    {p.root_query}
                  </p>
                </div>
                <StatusBadge status={p.status} />
                <button
                  onClick={(e) => onDelete(p.id, e)}
                  className="text-[var(--color-faint)] opacity-0 transition-opacity hover:text-[var(--color-danger)] group-hover:opacity-100"
                  aria-label={t("common.delete")}
                >
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      </div>
    </>
  );
}
