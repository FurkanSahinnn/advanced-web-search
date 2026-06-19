import { useEffect, useState } from "react";
import {
  Cpu,
  HardDrive,
  Save,
  CheckCircle2,
  Layers,
  Plug,
  XCircle,
} from "lucide-react";
import { api } from "../lib/api";
import { useLang } from "../lib/i18n";
import type {
  ModelMap,
  ScoreWeights as Weights,
  SearchDepth,
  SettingsOut,
  SettingsUpdate,
  TestLLMResult,
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
import { cn } from "../lib/cn";

const ROLES: (keyof ModelMap)[] = [
  "planner",
  "moderator",
  "synthesizer",
  "verifier",
];

const CUSTOM = "__custom__";

const DEPTHS: SearchDepth[] = ["quick", "standard", "deep", "exhaustive"];

export function Settings() {
  const { t } = useLang();
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

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
  const [useLocalLlm, setUseLocalLlm] = useState(true);
  const [keepThreshold, setKeepThreshold] = useState(0.5);
  const [maxSubtopics, setMaxSubtopics] = useState(6);
  const [resultsPerSource, setResultsPerSource] = useState(5);
  const [depth, setDepth] = useState<SearchDepth>("quick");
  const [maxResearchRounds, setMaxResearchRounds] = useState(3);
  const [gapMinSources, setGapMinSources] = useState(3);
  const [queryVariants, setQueryVariants] = useState(3);
  const [snowballTopK, setSnowballTopK] = useState(8);
  // which roles are in free-text mode
  const [customRole, setCustomRole] = useState<Record<string, boolean>>({});
  // LLM connection test
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestLLMResult | null>(null);

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      // Test the model the user has TYPED (the draft), not just the saved one,
      // so the result reflects exactly what's in the fields. Falls back to the
      // saved/effective model when every field is empty.
      const draft =
        modelMap.planner ||
        modelMap.synthesizer ||
        modelMap.moderator ||
        modelMap.verifier ||
        undefined;
      setTestResult(await api.testLlm(draft ? { model: draft } : undefined));
    } catch (e) {
      setTestResult({
        ok: false,
        provider: null,
        model: null,
        latency_ms: 0,
        sample: "",
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setTesting(false);
    }
  };

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSettings(s);
        setModelMap(s.model_map);
        setWeights(s.weights);
        setRequireApproval(s.require_approval);
        setUseLocalLlm(s.use_local_llm);
        setKeepThreshold(s.keep_threshold);
        setMaxSubtopics(s.max_subtopics);
        setResultsPerSource(s.results_per_source);
        setDepth((s.depth as SearchDepth) ?? "quick");
        setMaxResearchRounds(s.max_research_rounds);
        setGapMinSources(s.gap_min_sources);
        setQueryVariants(s.query_variants);
        setSnowballTopK(s.snowball_top_k);
      })
      .catch(() => setLoadError(true));
  }, []);

  const modelOptions = (() => {
    if (!settings) return [];
    const opts = new Set<string>();
    settings.llm.cloud_providers.forEach((p) => opts.add(p));
    settings.llm.ollama_models.forEach((m) => opts.add(m));
    Object.values(settings.model_map).forEach((m) => m && opts.add(m));
    Object.values(settings.llm.effective_models).forEach((m) => m && opts.add(m));
    return [...opts];
  })();

  const save = async () => {
    setSaving(true);
    setSaved(false);
    const body: SettingsUpdate = {
      model_map: modelMap,
      weights,
      require_approval: requireApproval,
      use_local_llm: useLocalLlm,
      keep_threshold: keepThreshold,
      max_subtopics: maxSubtopics,
      results_per_source: resultsPerSource,
      depth,
      max_research_rounds: maxResearchRounds,
      gap_min_sources: gapMinSources,
      query_variants: queryVariants,
      snowball_top_k: snowballTopK,
    };
    try {
      const updated = await api.patchSettings(body);
      setSettings(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
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
  const preset = settings.depth_presets?.[depth] ?? null;

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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Model assignments */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>{t("settings.models")}</CardTitle>
            <CardDescription>{t("settings.modelsHint")}</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {/* Free-text model id per agent. Type any litellm id (incl.
               openrouter/<slug>); the datalist only offers optional suggestions. */}
            <datalist id="model-suggestions">
              {Array.from(
                new Set([
                  ...modelOptions,
                  "openrouter/anthropic/claude-haiku-4.5",
                  "openrouter/anthropic/claude-sonnet-4.5",
                  "openrouter/openai/gpt-4o-mini",
                  "openrouter/google/gemini-2.5-flash",
                  "openrouter/deepseek/deepseek-chat",
                  "openrouter/meta-llama/llama-3.3-70b-instruct",
                  "openrouter/qwen/qwen-2.5-72b-instruct",
                ]),
              ).map((o) => (
                <option key={o} value={o} />
              ))}
            </datalist>
            {ROLES.map((role) => {
              const current = modelMap[role] ?? "";
              return (
                <div key={role}>
                  <label className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
                    {t(`settings.role.${role}`)}
                  </label>
                  <Input
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
                </div>
              );
            })}

            {/* Connection test */}
            <div className="sm:col-span-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={runTest}
                  disabled={testing}
                >
                  {testing ? (
                    <Spinner size={14} className="text-current" />
                  ) : (
                    <Plug size={14} />
                  )}
                  {testing
                    ? t("settings.testing")
                    : t("settings.testConnection")}
                </Button>

                {testResult && !testing && (
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 text-xs",
                      testResult.ok
                        ? "text-[var(--color-good)]"
                        : "text-[var(--color-danger)]",
                    )}
                  >
                    {testResult.ok ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <XCircle size={14} />
                    )}
                    {testResult.ok ? (
                      <span>
                        {t("settings.testOk")} · {testResult.latency_ms}ms
                        {testResult.model ? ` · ${testResult.model}` : ""}
                      </span>
                    ) : (
                      <span className="break-words">
                        {t("settings.testFailed")}
                        {testResult.error ? `: ${testResult.error}` : ""}
                      </span>
                    )}
                  </span>
                )}
              </div>
            </div>

            {/* Local LLM (Ollama) toggle. When OFF, the backend never probes
               Ollama (no ~1s Settings delay) and never falls back to a local
               model — only cloud keys are used. */}
            <div className="sm:col-span-2 border-t border-[var(--color-border)] pt-3">
              <label className="flex cursor-pointer items-center justify-between text-sm text-[var(--color-fg)]">
                {t("settings.useLocalLlm")}
                <input
                  type="checkbox"
                  checked={useLocalLlm}
                  onChange={(e) => setUseLocalLlm(e.target.checked)}
                  className="h-4 w-4 accent-[var(--color-accent)]"
                />
              </label>
              {!useLocalLlm && (
                <p className="mt-1 text-[11px] leading-snug text-[var(--color-muted)]">
                  {t("settings.useLocalLlmHint")}
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Search depth / Comprehensiveness */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers size={15} /> {t("settings.comprehensiveness")}
            </CardTitle>
            <CardDescription>
              {t("settings.comprehensivenessHint")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--color-muted)]">
                {t("settings.depth")}
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
              {preset && (
                <p className="mt-1.5 text-[10px] leading-snug text-[var(--color-faint)]">
                  {t("settings.presetImplies")}: {preset.max_subtopics}{" "}
                  {t("settings.preset.subtopics")} · {preset.max_research_rounds}{" "}
                  {t("settings.preset.rounds")} ·{" "}
                  {t("settings.preset.snowball")} {preset.snowball ? "✓" : "✗"} (
                  {preset.snowball_top_k}) · {t("settings.preset.bilingual")}{" "}
                  {preset.bilingual ? "✓" : "✗"} ·{" "}
                  {t("settings.preset.recursion")} {preset.recursion_depth}
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <NumberField
                label={t("settings.maxResearchRounds")}
                value={maxResearchRounds}
                min={1}
                max={5}
                onChange={setMaxResearchRounds}
              />
              <NumberField
                label={t("settings.gapMinSources")}
                value={gapMinSources}
                min={1}
                max={8}
                onChange={setGapMinSources}
              />
              <NumberField
                label={t("settings.queryVariants")}
                value={queryVariants}
                min={1}
                max={5}
                onChange={setQueryVariants}
              />
              <NumberField
                label={t("settings.snowballTopK")}
                value={snowballTopK}
                min={0}
                max={30}
                onChange={setSnowballTopK}
              />
            </div>
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

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted)]">
                  {t("settings.maxSubtopics")}
                </label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={maxSubtopics}
                  onChange={(e) =>
                    setMaxSubtopics(parseInt(e.target.value) || 1)
                  }
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--color-muted)]">
                  {t("settings.resultsPerSource")}
                </label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={resultsPerSource}
                  onChange={(e) =>
                    setResultsPerSource(parseInt(e.target.value) || 1)
                  }
                />
              </div>
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
              {settings.providers.map((p) => (
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

function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-[var(--color-muted)]">{label}</span>
        <span className="tabular-nums text-[var(--color-accent)]">{value}</span>
      </div>
      <Slider
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(e) => {
          const v = parseInt(e.target.value, 10);
          onChange(Number.isNaN(v) ? min : v);
        }}
      />
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
