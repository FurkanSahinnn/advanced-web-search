import type {
  ApprovalDecision,
  AskAnswer,
  CreateProjectResponse,
  ExportFormat,
  HealthResponse,
  ProjectCreate,
  ProjectDetail,
  ProbeResult,
  ProjectOut,
  ReportOut,
  RunOut,
  SetKeyResult,
  SettingsOut,
  SettingsUpdate,
  SourceOut,
  TestLLMResult,
  VaultResult,
} from "./types";

// Same origin in production; Vite proxies "/api" to the backend in dev.
const BASE = "";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const { json, headers, ...rest } = init ?? {};
  const opts: RequestInit = {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers ?? {}),
    },
  };
  if (json !== undefined) opts.body = JSON.stringify(json);

  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.message ?? detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),

  getSettings: () => request<SettingsOut>("/api/settings"),
  patchSettings: (body: SettingsUpdate) =>
    request<SettingsOut>("/api/settings", { method: "PATCH", json: body }),
  testLlm: (opts?: { role?: string; model?: string }) =>
    request<TestLLMResult>("/api/settings/test-llm", {
      method: "POST",
      json: opts ?? {},
    }),

  // --- Encrypted API-key vault + provider key management ---
  vaultSetup: (master_password: string) =>
    request<VaultResult>("/api/settings/vault/setup", {
      method: "POST",
      json: { master_password },
    }),
  vaultUnlock: (master_password: string) =>
    request<VaultResult>("/api/settings/vault/unlock", {
      method: "POST",
      json: { master_password },
    }),
  vaultLock: () =>
    request<{ ok: boolean }>("/api/settings/vault/lock", { method: "POST" }),
  vaultChangePassword: (old_password: string, new_password: string) =>
    request<VaultResult>("/api/settings/vault/change-password", {
      method: "POST",
      json: { old_password, new_password },
    }),
  vaultReset: () =>
    request<{ ok: boolean }>("/api/settings/vault/reset", {
      method: "POST",
      json: { confirm: true },
    }),

  setProviderKey: (provider: string, key: string, verify = true) =>
    request<SetKeyResult>("/api/settings/provider-key", {
      method: "PUT",
      json: { provider, key, verify },
    }),
  deleteProviderKey: (provider: string) =>
    request<VaultResult>(
      `/api/settings/provider-key/${encodeURIComponent(provider)}`,
      { method: "DELETE" },
    ),
  validateKey: (provider: string, key: string) =>
    request<ProbeResult>("/api/settings/validate-key", {
      method: "POST",
      json: { provider, key },
    }),
  testEndpoint: (base_url: string, model: string, api_key?: string) =>
    request<ProbeResult>("/api/settings/test-endpoint", {
      method: "POST",
      json: { base_url, model, ...(api_key ? { api_key } : {}) },
    }),

  listProjects: () => request<ProjectOut[]>("/api/projects"),
  createProject: (query: string, opts?: Omit<ProjectCreate, "query">) =>
    request<CreateProjectResponse>("/api/projects", {
      method: "POST",
      json: { query, ...(opts ?? {}) } satisfies ProjectCreate,
    }),
  getProject: (id: number | string) =>
    request<ProjectDetail>(`/api/projects/${id}`),
  deleteProject: (id: number | string) =>
    request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

  getRun: (runId: number | string) => request<RunOut>(`/api/runs/${runId}`),
  getSources: (runId: number | string, keptOnly = false) =>
    request<SourceOut[]>(
      `/api/runs/${runId}/sources?kept_only=${keptOnly ? "true" : "false"}`,
    ),
  getReport: (runId: number | string) =>
    request<ReportOut | null>(`/api/runs/${runId}/report`),
  getReports: (runId: number | string) =>
    request<ReportOut[]>(`/api/runs/${runId}/reports`),
  approve: (runId: number | string, decision: ApprovalDecision) =>
    request<{ ok: boolean }>(`/api/runs/${runId}/approve`, {
      method: "POST",
      json: decision,
    }),
  cancel: (runId: number | string) =>
    request<{ ok: boolean }>(`/api/runs/${runId}/cancel`, { method: "POST" }),

  // Ask-the-Report: a grounded follow-up answered only from this run's sources.
  askReport: (runId: number | string, question: string, language?: string) =>
    request<AskAnswer>(`/api/runs/${runId}/ask`, {
      method: "POST",
      json: { question, ...(language ? { language } : {}) },
    }),

  // Download URL for a run's export (Markdown/BibTeX/RIS/CSL-JSON/HTML).
  // `lang` selects which language's report to export (doc formats only;
  // reference formats are language-independent and ignore it).
  exportUrl: (
    runId: number,
    format: ExportFormat,
    keptOnly = true,
    lang?: string,
  ): string =>
    `${BASE}/api/runs/${runId}/export?format=${format}&kept_only=${keptOnly ? "true" : "false"}${
      lang ? `&lang=${encodeURIComponent(lang)}` : ""
    }`,

  // Fetch a single source's citation (BibTeX/RIS) as plain text.
  citeSource: async (
    sourceId: number,
    format: "bibtex" | "ris",
  ): Promise<string> => {
    const res = await fetch(
      `${BASE}/api/sources/${sourceId}/cite?format=${format}`,
      { headers: { Accept: "text/plain" } },
    );
    if (!res.ok) {
      throw new ApiError(res.status, res.statusText);
    }
    return res.text();
  },
};

export { ApiError };

export function streamUrl(runId: number | string): string {
  return `${BASE}/api/runs/${runId}/stream`;
}
