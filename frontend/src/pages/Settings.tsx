import { useEffect, useState } from "react";
import { Cpu, HardDrive, Save, CheckCircle2 } from "lucide-react";
import { api } from "../lib/api";
import { useLang } from "../lib/i18n";
import type {
  ModelMap,
  ScoreWeights as Weights,
  SettingsOut,
  SettingsUpdate,
} from "../lib/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Slider } from "../components/ui/slider";
import { Badge } from "../components/ui/badge";
import { Spinner } from "../components/ui/spinner";
import { ScoreWeights } from "../components/ScoreWeights";
import { ModelProviders } from "../components/ModelProviders";

const ROLES: (keyof ModelMap)[] = [
  "planner",
  "moderator",
  "synthesizer",
  "verifier",
];

const CUSTOM = "__custom__";

const CLOUD_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
  groq: "Groq",
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
};

export function Settings() {
  const { t } = useLang();
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // editable draft
  const [modelMap, setModelMap] = useState<ModelMap>({
    planner: null,
    moderator: null,
    synthesizer: null,
    verifier: null,
  });
  const [weights, setWeights] = useState<Weights>({
    relevance: 0.4,
    authority: 0.15,
    recency: 0.15,
    citation_impact: 0.15,
    evidence: 0.15,
  });
  const [requireApproval, setRequireApproval] = useState(false);
  const [keepThreshold, setKeepThreshold] = useState(0.5);
  // which roles are in free-text mode (model id not in the dropdown options)
  const [customRole, setCustomRole] = useState<Record<string, boolean>>({});

  const applySettings = (s: SettingsOut) => {
    setSettings(s);
    setModelMap(s.model_map);
    setWeights(s.weights);
    setRequireApproval(s.require_approval);
    setKeepThreshold(s.keep_threshold);
  };

  // Re-fetch settings (used by ModelProviders after vault/key/endpoint changes
  // so the page reflects new status without a full reload).
  const reload = async () => {
    try {
      applySettings(await api.getSettings());
    } catch {
      /* keep current view on a transient failure */
    }
  };

  useEffect(() => {
    api
      .getSettings()
      .then(applySettings)
      .catch(() => setLoadError(true));
  }, []);

  // Concrete model-id options for the per-role dropdowns (no bare provider
  // names — those aren't valid litellm ids). Deliberately excludes the editable
  // `modelMap` draft so a value the user is typing in a custom-role text box
  // doesn't get added to the options and flip the row out of free-text mode.
  const modelOptions = (() => {
    if (!settings) return [] as string[];
    const opts = new Set<string>();
    settings.llm.ollama_models.forEach((m) => opts.add(m));
    Object.values(settings.llm.effective_models).forEach((m) => m && opts.add(m));
    return [...opts];
  })();

  // Per-role backend picker options: each entry is a concrete, CORRECTLY-PREFIXED
  // litellm id (cloud provider default / ollama_chat tag / custom endpoint) so the
  // user can decide, per agent role, exactly which backend handles it.
  const roleOptions = (() => {
    if (!settings) return [] as { value: string; label: string }[];
    const out: { value: string; label: string }[] = [];
    settings.providers
      .filter((p) => p.kind === "cloud" && p.available)
      .forEach((p) => {
        const id = settings.cloud_defaults[p.name];
        if (id) {
          out.push({
            value: id,
            label: `${t("settings.backendCloud")} · ${CLOUD_LABEL[p.name] ?? p.name} (${id})`,
          });
        }
      });
    settings.llm.ollama_models.forEach((m) =>
      out.push({ value: `ollama_chat/${m}`, label: `${t("settings.backendOllama")} · ${m}` }),
    );
    const cm = settings.custom_endpoint.model;
    if (cm) {
      out.push({ value: `custom/${cm}`, label: `${t("settings.backendCustom")} · ${cm}` });
    }
    return out;
  })();
  const roleOptionValues = new Set(roleOptions.map((o) => o.value));

  const save = async () => {
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    const body: SettingsUpdate = {
      model_map: modelMap,
      weights,
      require_approval: requireApproval,
      keep_threshold: keepThreshold,
    };
    try {
      const updated = await api.patchSettings(body);
      setSettings(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  };

  if (loadError) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <p className="text-sm text-[var(--color-muted)]">{t("common.error")}</p>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size={22} />
      </div>
    );
  }

  const hw = settings.hardware;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold tracking-tight text-[var(--color-fg)]">
          {t("settings.title")}
        </h1>
        <Button onClick={save} disabled={saving}>
          {saving ? (
            <Spinner size={15} className="text-current" />
          ) : saved ? (
            <CheckCircle2 size={15} />
          ) : (
            <Save size={15} />
          )}
          {saving
            ? t("settings.saving")
            : saved
              ? t("settings.saved")
              : t("settings.save")}
        </Button>
      </div>

      {saveError && (
        <div className="mb-4 rounded-[var(--radius)] border border-[color-mix(in_srgb,var(--color-danger)_40%,transparent)] bg-[color-mix(in_srgb,var(--color-danger)_12%,transparent)] px-3 py-2 text-xs text-[var(--color-danger)]">
          {t("common.error")}: {saveError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* AI models & providers: encrypted vault, cloud keys + verify,
            local Ollama, self-hosted OpenAI-compatible server. */}
        <ModelProviders settings={settings} t={t} onChanged={reload} />

        {/* Per-role model assignment (saved with the main Save button). */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>{t("settings.roles")}</CardTitle>
            <CardDescription>{t("settings.rolesHint")}</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <datalist id="model-suggestions">
              {Array.from(
                new Set([
                  ...modelOptions,
                  "openrouter/anthropic/claude-haiku-4.5",
                  "openrouter/openai/gpt-4o-mini",
                  "openrouter/google/gemini-2.5-flash",
                  "openrouter/deepseek/deepseek-chat",
                ]),
              ).map((o) => (
                <option key={o} value={o} />
              ))}
            </datalist>
            {ROLES.map((role) => {
              const current = modelMap[role] ?? "";
              const isCustom =
                customRole[role] || (!!current && !roleOptionValues.has(current));
              return (
                <div key={role}>
                  <label className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
                    {t(`settings.role.${role}`)}
                  </label>
                  <Select
                    value={isCustom ? CUSTOM : current}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === CUSTOM) {
                        setCustomRole((c) => ({ ...c, [role]: true }));
                      } else {
                        setCustomRole((c) => ({ ...c, [role]: false }));
                        setModelMap((m) => ({ ...m, [role]: v || null }));
                      }
                    }}
                  >
                    <option value="">{t("settings.role.default")}</option>
                    {roleOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                    <option value={CUSTOM}>{t("settings.custom")}</option>
                  </Select>
                  {isCustom && (
                    <Input
                      className="mt-1.5"
                      list="model-suggestions"
                      value={current}
                      placeholder="örn. openrouter/anthropic/claude-3.5-sonnet"
                      spellCheck={false}
                      autoCapitalize="off"
                      autoCorrect="off"
                      onChange={(e) =>
                        setModelMap((m) => ({ ...m, [role]: e.target.value || null }))
                      }
                    />
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Weights */}
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.weights")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ScoreWeights value={weights} onChange={setWeights} />
          </CardContent>
        </Card>

        {/* Run parameters */}
        <Card>
          <CardHeader>
            <CardTitle>{t("nav.research")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex cursor-pointer items-center justify-between text-sm text-[var(--color-fg)]">
              {t("settings.requireApproval")}
              <input
                type="checkbox"
                checked={requireApproval}
                onChange={(e) => setRequireApproval(e.target.checked)}
                className="h-4 w-4 accent-[var(--color-accent)]"
              />
            </label>

            <div>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-[var(--color-fg)]">
                  {t("settings.keepThreshold")}
                </span>
                <span className="tabular-nums text-[var(--color-accent)]">
                  {keepThreshold.toFixed(2)}
                </span>
              </div>
              <Slider
                min={0}
                max={1}
                step={0.01}
                value={keepThreshold}
                onChange={(e) => setKeepThreshold(parseFloat(e.target.value))}
              />
            </div>

          </CardContent>
        </Card>

        {/* Hardware */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu size={15} /> {t("settings.hardware")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-lg border border-[color-mix(in_srgb,var(--color-accent)_35%,transparent)] bg-[var(--color-accent-soft)] px-3 py-2">
              <p className="text-[11px] text-[var(--color-muted)]">
                {t("settings.recommended")}
              </p>
              <p className="text-sm font-semibold text-[var(--color-accent)]">
                {hw.recommended_local_model}
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <Stat label={t("settings.totalRam")} value={`${hw.total_ram_gb} GB`} />
              <Stat
                label={t("settings.availableRam")}
                value={`${hw.available_ram_gb} GB`}
              />
              <Stat label={t("settings.cpu")} value={String(hw.cpu_count)} />
            </div>
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-[var(--color-muted)]">
                <HardDrive size={13} /> {t("settings.localOptions")}
              </p>
              <ul className="space-y-1">
                {hw.options.map((o) => (
                  <li
                    key={o.model}
                    className="flex items-center justify-between rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2.5 py-1.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-xs text-[var(--color-fg)]">
                        {o.label}
                      </p>
                      <p className="text-[10px] text-[var(--color-faint)]">
                        {o.model} · ≥{o.min_ram_gb} GB
                      </p>
                    </div>
                    <Badge variant={o.fits ? "good" : "default"}>
                      {o.fits ? t("settings.fits") : t("settings.tooBig")}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>

        {/* Providers */}
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.providers")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {/* Cloud LLM providers are managed in the section above; here we
                 list only the web/academic sources + local Ollama status. */}
              {settings.providers
                .filter((p) => p.kind !== "cloud")
                .map((p) => (
                <li
                  key={`${p.kind}-${p.name}`}
                  className="flex items-center justify-between rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2.5 py-1.5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs text-[var(--color-fg)]">
                      {p.name}
                    </p>
                    <p className="text-[10px] uppercase tracking-wide text-[var(--color-faint)]">
                      {p.kind}
                      {p.note ? ` · ${p.note}` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {p.requires_key && (
                      <Badge variant="warn">{t("settings.requiresKey")}</Badge>
                    )}
                    <Badge variant={p.available ? "good" : "default"}>
                      {p.available
                        ? t("settings.available")
                        : t("settings.unavailable")}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1.5">
      <p className="text-sm font-semibold text-[var(--color-fg)]">{value}</p>
      <p className="text-[10px] text-[var(--color-faint)]">{label}</p>
    </div>
  );
}
