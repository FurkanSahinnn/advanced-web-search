import { useEffect, useState } from "react";
import {
  CheckCircle2,
  XCircle,
  Lock,
  Unlock,
  KeyRound,
  ShieldCheck,
  Server,
  Cpu,
  Plug,
  Trash2,
  RefreshCw,
} from "lucide-react";
import { api } from "../lib/api";
import type { ProbeResult, SettingsOut, SettingsUpdate, TestLLMResult } from "../lib/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Select } from "./ui/select";
import { Badge } from "./ui/badge";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/cn";

type T = (k: string) => string;

interface Props {
  settings: SettingsOut;
  t: T;
  onChanged: () => Promise<void> | void;
}

const CLOUD_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Google Gemini",
  groq: "Groq",
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
};

export function ModelProviders({ settings, t, onChanged }: Props) {
  const vault = settings.vault;
  const cloud = settings.providers.filter((p) => p.kind === "cloud");
  const availableCloud = cloud.filter((p) => p.available);

  // --- connection draft (saved together via the section Save button) ---
  const [activeValue, setActiveValue] = useState<string>(() => {
    const a = settings.active_llm;
    if (a.kind === "cloud" && a.provider) return `cloud:${a.provider}`;
    if (a.kind === "ollama") return "ollama";
    if (a.kind === "custom") return "custom";
    return "auto";
  });
  const [useLocalLlm, setUseLocalLlm] = useState(settings.use_local_llm);
  const [ollamaUrl, setOllamaUrl] = useState(settings.ollama_base_url);
  const [localModel, setLocalModel] = useState(settings.local_model ?? "");
  const [customUrl, setCustomUrl] = useState(settings.custom_endpoint.base_url ?? "");
  const [customModel, setCustomModel] = useState(settings.custom_endpoint.model ?? "");
  const [customKey, setCustomKey] = useState("");
  const [savingConn, setSavingConn] = useState(false);
  const [savedConn, setSavedConn] = useState(false);

  // --- transient action state ---
  const [busy, setBusy] = useState<string | null>(null); // a stable key for the in-flight action
  const [vaultErr, setVaultErr] = useState<string | null>(null);
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [keyMsg, setKeyMsg] = useState<
    Record<string, { ok: boolean; text: string } | undefined>
  >({});
  const [status, setStatus] = useState<TestLLMResult | null>(null);
  const [customTest, setCustomTest] = useState<ProbeResult | null>(null);

  // vault password fields
  const [pw1, setPw1] = useState("");
  const [pw2, setPw2] = useState("");
  const [unlockPw, setUnlockPw] = useState("");
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [showChange, setShowChange] = useState(false);

  // useState initialisers only run once; when the parent re-fetches settings
  // after a vault/key/connection change, re-sync the connection drafts so the
  // controls reflect the persisted server state instead of going stale.
  useEffect(() => {
    const a = settings.active_llm;
    setActiveValue(
      a.kind === "cloud" && a.provider
        ? `cloud:${a.provider}`
        : a.kind === "ollama"
          ? "ollama"
          : a.kind === "custom"
            ? "custom"
            : "auto",
    );
    setUseLocalLlm(settings.use_local_llm);
    setOllamaUrl(settings.ollama_base_url);
    setLocalModel(settings.local_model ?? "");
    setCustomUrl(settings.custom_endpoint.base_url ?? "");
    setCustomModel(settings.custom_endpoint.model ?? "");
  }, [settings]);

  const reload = async () => {
    await onChanged();
  };

  // ----- status test -----
  const runStatusTest = async () => {
    setBusy("status");
    setStatus(null);
    try {
      setStatus(await api.testLlm());
    } catch (e) {
      setStatus({
        ok: false,
        provider: null,
        model: null,
        latency_ms: 0,
        sample: "",
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setBusy(null);
    }
  };

  // ----- vault lifecycle -----
  const doSetup = async () => {
    setVaultErr(null);
    if (pw1.length < 8) return setVaultErr(t("settings.vaultPasswordShort"));
    if (pw1 !== pw2) return setVaultErr(t("settings.vaultPasswordMismatch"));
    setBusy("vault");
    try {
      const r = await api.vaultSetup(pw1);
      if (!r.ok) setVaultErr(r.error || t("common.error"));
      else {
        setPw1("");
        setPw2("");
        await reload();
      }
    } finally {
      setBusy(null);
    }
  };

  const doUnlock = async () => {
    setVaultErr(null);
    setBusy("vault");
    try {
      const r = await api.vaultUnlock(unlockPw);
      if (!r.ok) setVaultErr(t("settings.vaultWrongPassword"));
      else {
        setUnlockPw("");
        await reload();
      }
    } finally {
      setBusy(null);
    }
  };

  const doLock = async () => {
    setVaultErr(null);
    setBusy("vault");
    try {
      await api.vaultLock();
      await reload();
    } catch (e) {
      setVaultErr(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setBusy(null);
    }
  };

  const doChangePassword = async () => {
    setVaultErr(null);
    if (newPw.length < 8) return setVaultErr(t("settings.vaultPasswordShort"));
    setBusy("vault");
    try {
      const r = await api.vaultChangePassword(oldPw, newPw);
      if (!r.ok) setVaultErr(r.error || t("settings.vaultWrongPassword"));
      else {
        setOldPw("");
        setNewPw("");
        setShowChange(false);
        await reload();
      }
    } finally {
      setBusy(null);
    }
  };

  const doReset = async () => {
    if (!window.confirm(t("settings.vaultResetConfirm"))) return;
    setVaultErr(null);
    setBusy("vault");
    try {
      await api.vaultReset();
      await reload();
    } catch (e) {
      setVaultErr(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setBusy(null);
    }
  };

  // ----- cloud key management -----
  const verifyAndStore = async (provider: string) => {
    const key = (keyDraft[provider] || "").trim();
    if (!key) return;
    setBusy(`key:${provider}`);
    setKeyMsg((m) => ({ ...m, [provider]: undefined }));
    try {
      const r = await api.setProviderKey(provider, key, true);
      if (r.ok) {
        setKeyDraft((d) => ({ ...d, [provider]: "" }));
        setKeyMsg((m) => ({ ...m, [provider]: { ok: true, text: t("settings.valid") } }));
        await reload();
      } else {
        const why = r.validation?.error || r.error || t("settings.invalid");
        setKeyMsg((m) => ({ ...m, [provider]: { ok: false, text: why } }));
      }
    } catch (e) {
      setKeyMsg((m) => ({
        ...m,
        [provider]: { ok: false, text: e instanceof Error ? e.message : String(e) },
      }));
    } finally {
      setBusy(null);
    }
  };

  const removeKey = async (provider: string) => {
    setBusy(`key:${provider}`);
    try {
      await api.deleteProviderKey(provider);
      setKeyMsg((m) => ({ ...m, [provider]: undefined }));
      await reload();
    } catch (e) {
      setKeyMsg((m) => ({
        ...m,
        [provider]: { ok: false, text: e instanceof Error ? e.message : String(e) },
      }));
    } finally {
      setBusy(null);
    }
  };

  // ----- custom endpoint test -----
  const testCustom = async () => {
    setBusy("custom");
    setCustomTest(null);
    try {
      setCustomTest(await api.testEndpoint(customUrl.trim(), customModel.trim(), customKey.trim() || undefined));
    } finally {
      setBusy(null);
    }
  };

  // ----- save connection settings (non-secret + optional custom key) -----
  const saveConnection = async () => {
    setSavingConn(true);
    setSavedConn(false);
    try {
      let kind: "auto" | "cloud" | "ollama" | "custom" = "auto";
      let provider: string | null = null;
      if (activeValue.startsWith("cloud:")) {
        kind = "cloud";
        provider = activeValue.slice("cloud:".length);
      } else if (activeValue === "ollama") kind = "ollama";
      else if (activeValue === "custom") kind = "custom";

      const body: SettingsUpdate = {
        active_llm: { kind, provider },
        use_local_llm: useLocalLlm,
        ollama_base_url: ollamaUrl.trim(),
        local_model: localModel.trim() || null,
        custom_base_url: customUrl.trim() || null,
        custom_model: customModel.trim() || null,
      };
      await api.patchSettings(body);
      // Optionally seal a custom-endpoint key (needs an unlocked vault).
      if (customKey.trim() && vault.unlocked) {
        await api.setProviderKey("custom", customKey.trim(), false);
        setCustomKey("");
      }
      await reload();
      setSavedConn(true);
      setTimeout(() => setSavedConn(false), 2500);
    } finally {
      setSavingConn(false);
    }
  };

  const modeText =
    settings.llm.mode === "none"
      ? t("settings.modeNone")
      : `${settings.llm.active_provider ?? settings.llm.mode}`;

  return (
    <Card className="md:col-span-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound size={15} /> {t("settings.provSection")}
        </CardTitle>
        <CardDescription>{t("settings.provSectionHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Status strip */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius)] border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-[var(--color-muted)]">{t("settings.statusLabel")}:</span>
            <Badge variant={settings.llm.mode === "none" ? "default" : "good"}>{modeText}</Badge>
            {settings.llm.effective_models.planner && (
              <span className="text-[11px] text-[var(--color-faint)]">
                {settings.llm.effective_models.planner}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {status && !busy && (
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-xs",
                  status.ok ? "text-[var(--color-good)]" : "text-[var(--color-danger)]",
                )}
              >
                {status.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                {status.ok
                  ? `${t("settings.testOk")} · ${status.latency_ms}ms`
                  : `${t("settings.testFailed")}${status.error ? `: ${status.error}` : ""}`}
              </span>
            )}
            <Button variant="secondary" size="sm" onClick={runStatusTest} disabled={busy === "status"}>
              {busy === "status" ? <Spinner size={13} className="text-current" /> : <Plug size={13} />}
              {t("settings.testConnection")}
            </Button>
          </div>
        </div>

        {/* Active backend selector */}
        <div>
          <label className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
            {t("settings.activeBackend")}
          </label>
          <Select value={activeValue} onChange={(e) => setActiveValue(e.target.value)}>
            <option value="auto">{t("settings.backendAuto")}</option>
            {availableCloud.map((p) => (
              <option key={p.name} value={`cloud:${p.name}`}>
                {t("settings.backendCloud")} — {CLOUD_LABEL[p.name] ?? p.name}
              </option>
            ))}
            <option value="ollama">{t("settings.backendOllama")}</option>
            <option value="custom">{t("settings.backendCustom")}</option>
          </Select>
        </div>

        {/* --- Cloud providers (vault) --- */}
        <div className="rounded-[var(--radius)] border border-[var(--color-border)] p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-fg)]">
              <ShieldCheck size={14} /> {t("settings.cloudProviders")}
            </p>
            {vault.configured && (
              <Badge variant={vault.unlocked ? "good" : "warn"}>
                {vault.unlocked ? t("settings.vaultUnlocked") : t("settings.vaultLocked")}
              </Badge>
            )}
          </div>
          <p className="mb-3 text-[11px] leading-snug text-[var(--color-muted)]">
            {t("settings.cloudProvidersHint")}
          </p>

          {/* Vault gate */}
          {!vault.configured ? (
            <div className="mb-3 space-y-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
              <p className="text-[11px] leading-snug text-[var(--color-muted)]">
                {t("settings.vaultSetupHint")}
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input
                  type="password"
                  placeholder={t("settings.vaultMasterPassword")}
                  value={pw1}
                  onChange={(e) => setPw1(e.target.value)}
                  autoComplete="new-password"
                />
                <Input
                  type="password"
                  placeholder={t("settings.vaultConfirmPassword")}
                  value={pw2}
                  onChange={(e) => setPw2(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <Button size="sm" onClick={doSetup} disabled={busy === "vault"}>
                {busy === "vault" ? <Spinner size={13} className="text-current" /> : <Lock size={13} />}
                {t("settings.vaultSetBtn")}
              </Button>
            </div>
          ) : !vault.unlocked ? (
            <div className="mb-3 space-y-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
              <p className="text-[11px] text-[var(--color-muted)]">{t("settings.vaultLockedHint")}</p>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  type="password"
                  placeholder={t("settings.vaultMasterPassword")}
                  value={unlockPw}
                  onChange={(e) => setUnlockPw(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && doUnlock()}
                  className="max-w-xs"
                  autoComplete="current-password"
                />
                <Button size="sm" onClick={doUnlock} disabled={busy === "vault"}>
                  {busy === "vault" ? <Spinner size={13} className="text-current" /> : <Unlock size={13} />}
                  {t("settings.vaultUnlock")}
                </Button>
                <Button variant="ghost" size="sm" onClick={doReset} disabled={busy === "vault"}>
                  {t("settings.vaultReset")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Button variant="secondary" size="sm" onClick={doLock} disabled={busy === "vault"}>
                <Lock size={13} /> {t("settings.vaultLock")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setShowChange((s) => !s)}>
                {t("settings.vaultChangePassword")}
              </Button>
              <Button variant="ghost" size="sm" onClick={doReset} disabled={busy === "vault"}>
                {t("settings.vaultReset")}
              </Button>
            </div>
          )}

          {showChange && vault.unlocked && (
            <div className="mb-3 grid gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3 sm:grid-cols-2">
              <Input
                type="password"
                placeholder={t("settings.vaultOldPassword")}
                value={oldPw}
                onChange={(e) => setOldPw(e.target.value)}
                autoComplete="current-password"
              />
              <Input
                type="password"
                placeholder={t("settings.vaultNewPassword")}
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                autoComplete="new-password"
              />
              <Button size="sm" onClick={doChangePassword} disabled={busy === "vault"} className="sm:col-span-2">
                {t("settings.vaultChangePassword")}
              </Button>
            </div>
          )}

          {vaultErr && <p className="mb-2 text-xs text-[var(--color-danger)]">{vaultErr}</p>}

          {/* Per-provider rows */}
          <ul className="space-y-1.5">
            {cloud.map((p) => {
              const msg = keyMsg[p.name];
              const isBusy = busy === `key:${p.name}`;
              return (
                <li
                  key={p.name}
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2.5 py-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-[var(--color-fg)]">{CLOUD_LABEL[p.name] ?? p.name}</span>
                    <div className="flex items-center gap-1.5">
                      {p.key_set ? (
                        <Badge variant="good">
                          {p.key_source === "env" ? t("settings.keyFromEnv") : t("settings.stored")}
                          {p.key_hint ? ` ·••${p.key_hint}` : ""}
                        </Badge>
                      ) : (
                        <Badge variant="default">{t("settings.none")}</Badge>
                      )}
                    </div>
                  </div>

                  {vault.unlocked ? (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Input
                        type="password"
                        placeholder={t("settings.apiKeyPlaceholder")}
                        value={keyDraft[p.name] ?? ""}
                        onChange={(e) => setKeyDraft((d) => ({ ...d, [p.name]: e.target.value }))}
                        className="max-w-xs"
                        autoComplete="off"
                        spellCheck={false}
                      />
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => verifyAndStore(p.name)}
                        disabled={isBusy || !(keyDraft[p.name] || "").trim()}
                      >
                        {isBusy ? <Spinner size={13} className="text-current" /> : <CheckCircle2 size={13} />}
                        {isBusy ? t("settings.verifying") : t("settings.verify")}
                      </Button>
                      {p.key_set && p.key_source === "vault" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => removeKey(p.name)}
                          disabled={isBusy}
                          aria-label={t("common.delete")}
                        >
                          <Trash2 size={13} />
                        </Button>
                      )}
                      {msg && (
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 text-xs",
                            msg.ok ? "text-[var(--color-good)]" : "text-[var(--color-danger)]",
                          )}
                        >
                          {msg.ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                          <span className="break-words">{msg.text}</span>
                        </span>
                      )}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {!vault.unlocked && vault.configured && (
            <p className="mt-2 text-[11px] text-[var(--color-muted)]">{t("settings.unlockToManage")}</p>
          )}
        </div>

        {/* --- Local (Ollama) --- */}
        <div className="rounded-[var(--radius)] border border-[var(--color-border)] p-3">
          <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-[var(--color-fg)]">
            <Cpu size={14} /> {t("settings.localOllama")}
          </p>
          <label className="mb-2 flex cursor-pointer items-center justify-between text-sm text-[var(--color-fg)]">
            {t("settings.useLocalLlm")}
            <input
              type="checkbox"
              checked={useLocalLlm}
              onChange={(e) => setUseLocalLlm(e.target.checked)}
              className="h-4 w-4 accent-[var(--color-accent)]"
            />
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] text-[var(--color-muted)]">{t("settings.ollamaUrl")}</label>
              <Input
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
                placeholder="http://localhost:11434"
                spellCheck={false}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--color-muted)]">{t("settings.localModelLabel")}</label>
              <Select value={localModel} onChange={(e) => setLocalModel(e.target.value)}>
                <option value="">{t("settings.autoBySize")}</option>
                {settings.llm.ollama_models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                {/* keep a previously-saved custom local model selectable */}
                {localModel && !settings.llm.ollama_models.includes(localModel) && (
                  <option value={localModel}>{localModel}</option>
                )}
              </Select>
            </div>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px]">
            {settings.llm.ollama_available ? (
              <span className="inline-flex items-center gap-1 text-[var(--color-good)]">
                <CheckCircle2 size={12} /> {t("settings.connected")} — {settings.llm.ollama_models.length}{" "}
                {t("settings.modelsFound")}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[var(--color-muted)]">
                <RefreshCw size={12} /> {t("settings.notConnected")}
              </span>
            )}
          </div>
        </div>

        {/* --- Custom OpenAI-compatible server --- */}
        <div className="rounded-[var(--radius)] border border-[var(--color-border)] p-3">
          <p className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-[var(--color-fg)]">
            <Server size={14} /> {t("settings.customServer")}
          </p>
          <p className="mb-2 text-[11px] text-[var(--color-muted)]">{t("settings.customServerHint")}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="mb-1 block text-[11px] text-[var(--color-muted)]">{t("settings.serverUrl")}</label>
              <Input
                value={customUrl}
                onChange={(e) => setCustomUrl(e.target.value)}
                placeholder="http://localhost:1234/v1"
                spellCheck={false}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--color-muted)]">{t("settings.modelName")}</label>
              <Input value={customModel} onChange={(e) => setCustomModel(e.target.value)} spellCheck={false} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--color-muted)]">
                {t("settings.apiKeyOptional")}
                {!vault.unlocked ? ` — ${t("settings.vaultLocked")}` : ""}
              </label>
              <Input
                type="password"
                value={customKey}
                onChange={(e) => setCustomKey(e.target.value)}
                disabled={!vault.unlocked}
                autoComplete="off"
              />
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={testCustom}
              disabled={busy === "custom" || !customUrl.trim() || !customModel.trim()}
            >
              {busy === "custom" ? <Spinner size={13} className="text-current" /> : <Plug size={13} />}
              {t("settings.testConnection")}
            </Button>
            {customTest && busy !== "custom" && (
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-xs",
                  customTest.ok ? "text-[var(--color-good)]" : "text-[var(--color-danger)]",
                )}
              >
                {customTest.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                {customTest.ok
                  ? `${t("settings.testOk")} · ${customTest.latency_ms}ms`
                  : `${t("settings.testFailed")}${customTest.error ? `: ${customTest.error}` : ""}`}
              </span>
            )}
          </div>
        </div>

        {/* Section save (non-secret connection settings) */}
        <div className="flex items-center gap-2">
          <Button onClick={saveConnection} disabled={savingConn}>
            {savingConn ? (
              <Spinner size={14} className="text-current" />
            ) : savedConn ? (
              <CheckCircle2 size={14} />
            ) : (
              <ShieldCheck size={14} />
            )}
            {savedConn ? t("settings.applied") : t("settings.applyConnection")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
