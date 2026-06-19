import { useEffect, useRef, useState } from "react";
import { Download, ChevronDown, FileDown } from "lucide-react";
import { api } from "../lib/api";
import { useLang } from "../lib/i18n";
import { langKey } from "../lib/languages";
import type { ExportFormat } from "../lib/types";
import { Button } from "./ui/button";
import { cn } from "../lib/cn";

const ITEMS: { format: ExportFormat; labelKey: string }[] = [
  { format: "markdown", labelKey: "export.markdown" },
  { format: "bibtex", labelKey: "export.bibtex" },
  { format: "ris", labelKey: "export.ris" },
  { format: "csl", labelKey: "export.csl" },
  { format: "html", labelKey: "export.html" },
];

// Document formats are language-specific (one file per report language).
// Reference formats (BibTeX/RIS/CSL) describe the sources only and are
// language-independent, so they never carry a &lang= parameter.
const LANG_AWARE_FORMATS: ReadonlySet<ExportFormat> = new Set<ExportFormat>([
  "markdown",
  "html",
]);

export function ExportMenu({
  runId,
  disabled,
  className,
  languages,
  activeLang,
}: {
  runId: number | null;
  disabled?: boolean;
  className?: string;
  languages?: string[];
  activeLang?: string;
}) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [exportLang, setExportLang] = useState<string | undefined>(
    activeLang ?? languages?.[0],
  );

  // Keep the chosen export language in sync with the report the user is
  // currently viewing (and with the available languages) as they change.
  useEffect(() => {
    setExportLang((prev) => {
      const next = activeLang ?? prev ?? languages?.[0];
      if (next && languages && languages.length > 0 && !languages.includes(next)) {
        return languages[0];
      }
      return next;
    });
  }, [activeLang, languages]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const isDisabled = disabled || runId == null;
  const multiLang = (languages?.length ?? 0) > 1;

  // Append &lang= only for language-aware (document) formats when a language
  // is selected; reference formats are returned unchanged.
  const withLang = (url: string, format: ExportFormat): string =>
    exportLang && LANG_AWARE_FORMATS.has(format)
      ? `${url}&lang=${encodeURIComponent(exportLang)}`
      : url;

  // "PDF" is not a download: open the print-friendly HTML inline in a new tab.
  // The backend serves it with an auto-print script, so the browser renders the
  // report and opens its print dialog → the user picks "Save as PDF".
  const openPdf = () => {
    if (runId == null) return;
    setOpen(false);
    const base = `/api/runs/${runId}/export?format=html&print=true&kept_only=true`;
    window.open(
      exportLang ? `${base}&lang=${encodeURIComponent(exportLang)}` : base,
      "_blank",
      "noopener,noreferrer",
    );
  };

  return (
    <div ref={wrapRef} className={cn("relative", className)}>
      <Button
        variant="secondary"
        size="sm"
        disabled={isDisabled}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Download size={14} />
        {t("export.menu")}
        <ChevronDown size={13} />
      </Button>

      {open && runId != null && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-1 min-w-[12rem] overflow-hidden rounded-[var(--radius)] border border-[var(--color-border)] bg-[var(--color-elevated)] py-1 shadow-lg"
        >
          {multiLang && (
            <>
              <div className="px-3 pb-1 pt-1.5 text-[0.65rem] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
                {t("export.language")}
              </div>
              <div className="flex flex-wrap gap-1 px-3 pb-1.5">
                {languages!.map((code) => {
                  const selected = code === exportLang;
                  return (
                    <button
                      key={code}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => setExportLang(code)}
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[0.7rem] font-medium transition-colors",
                        selected
                          ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                          : "border-[var(--color-border)] text-[var(--color-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-accent)]",
                      )}
                    >
                      {t(langKey(code))}
                    </button>
                  );
                })}
              </div>
              <div className="my-1 border-t border-[var(--color-border)]" />
            </>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={openPdf}
            title={t("export.pdf.hint")}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-accent)]"
          >
            <FileDown size={13} />
            {t("export.pdf")}
          </button>
          <div className="my-1 border-t border-[var(--color-border)]" />
          {ITEMS.map((it) => (
            <a
              key={it.format}
              role="menuitem"
              href={withLang(api.exportUrl(runId, it.format, true), it.format)}
              download
              target={it.format === "html" ? "_blank" : undefined}
              rel="noreferrer noopener"
              onClick={() => setOpen(false)}
              className="block px-3 py-1.5 text-xs text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-accent)]"
            >
              {t(it.labelKey)}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
