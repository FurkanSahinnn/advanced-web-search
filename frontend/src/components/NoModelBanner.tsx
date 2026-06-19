import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, X } from "lucide-react";
import { api } from "../lib/api";
import { useLang } from "../lib/i18n";
import type { LLMMode } from "../lib/types";

// Module-level cache so the banner doesn't re-fetch /api/settings on every
// mount/navigation. `undefined` = not loaded yet, `null` = load failed.
let _modeCache: LLMMode | null | undefined = undefined;
let _inflight: Promise<LLMMode | null> | null = null;

async function loadMode(): Promise<LLMMode | null> {
  if (_modeCache !== undefined) return _modeCache;
  if (!_inflight) {
    _inflight = api
      .getSettings()
      .then((s) => {
        _modeCache = s.llm.mode;
        return _modeCache;
      })
      .catch(() => {
        _modeCache = null;
        return null;
      })
      .finally(() => {
        _inflight = null;
      });
  }
  return _inflight;
}

/** Allow other screens (e.g. Settings save) to refresh the cached LLM mode. */
export function invalidateModelModeCache() {
  _modeCache = undefined;
}

/**
 * Prominent, dismissible warning shown when no LLM is configured
 * (settings.llm.mode === "none"). Rendered on Home and Research.
 */
export function NoModelBanner() {
  const { t } = useLang();
  const [mode, setMode] = useState<LLMMode | null | undefined>(_modeCache);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let active = true;
    loadMode().then((m) => active && setMode(m ?? undefined));
    return () => {
      active = false;
    };
  }, []);

  if (dismissed || mode !== "none") return null;

  return (
    <div
      role="alert"
      className="flex items-start gap-2.5 border-b border-[color-mix(in_srgb,var(--color-warn)_45%,transparent)] bg-[color-mix(in_srgb,var(--color-warn)_14%,transparent)] px-4 py-2.5 text-xs text-[var(--color-warn)]"
    >
      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
      <p className="flex-1 leading-snug">
        {t("banner.noModel")}{" "}
        <Link
          to="/settings"
          className="font-semibold underline underline-offset-2 hover:opacity-80"
        >
          {t("banner.noModel.link")}
        </Link>
      </p>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label={t("banner.dismiss")}
        className="shrink-0 rounded p-0.5 opacity-70 transition-opacity hover:opacity-100"
      >
        <X size={14} />
      </button>
    </div>
  );
}
