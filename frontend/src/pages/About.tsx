import {
  BookOpen,
  Gauge,
  UserCheck,
  Repeat,
  Snowflake,
  Languages,
  Eye,
  TerminalSquare,
  Cpu,
  Boxes,
  Download,
  GitPullRequest,
  Layers,
  FlaskConical,
  PlayCircle,
  Lightbulb,
  Scale,
  Globe,
  BadgeCheck,
  Route,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import { useLang, type Lang } from "../lib/i18n";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "../components/ui/card";
import { Tabs, TabsContent } from "../components/ui/tabs";
import { MermaidDiagram } from "../components/MermaidDiagram";
import { cn } from "../lib/cn";

/* ────────────────────────────────────────────────────────────────────
   Diagram sources. Each is a function of `lang` so the node labels are
   localized (TR default + EN). The TR versions are authoritative; EN
   versions are faithful translations of the labels.
   ──────────────────────────────────────────────────────────────────── */

const lifecycle = (lang: Lang) =>
  lang === "tr"
    ? `flowchart LR
  U["👤 Araştırmacı"] -->|"soru + derinlik"| FE["React Arayüz"]
  FE -->|"POST /projects"| API["FastAPI"]
  API -->|"run başlat"| G["LangGraph Çok-Ajan Motoru"]
  G <-->|"durum + checkpoint"| DB[("SQLite + sqlite-vec + FTS5")]
  G -->|"SSE canlı olaylar"| FE
  G -->|"atıflı rapor"| API
  API -->|"Markdown · BibTeX · RIS · HTML"| FE`
    : `flowchart LR
  U["👤 Researcher"] -->|"question + depth"| FE["React UI"]
  FE -->|"POST /projects"| API["FastAPI"]
  API -->|"start run"| G["LangGraph Multi-Agent Engine"]
  G <-->|"state + checkpoint"| DB[("SQLite + sqlite-vec + FTS5")]
  G -->|"SSE live events"| FE
  G -->|"cited report"| API
  API -->|"Markdown · BibTeX · RIS · HTML"| FE`;

/* Shared shape/colour taxonomy for the agent graph. Node FILL+BORDER encode the
   category (indigo = LLM agent, blue = deterministic step, amber = decision /
   human gate, grey = I/O terminal); the legend under the diagram explains it. */
const AGENT_CLASSDEFS = `
  classDef io fill:#0e1013,stroke:#64748b,color:#cbd5e1;
  classDef agent fill:#1e1b4b,stroke:#5B4BE6,color:#e0e7ff;
  classDef step fill:#0f1b2d,stroke:#3b82f6,color:#dbeafe;
  classDef gate fill:#1c1406,stroke:#f59e0b,color:#fde68a;
  class S,E io;
  class P,M,R,G,SY agent;
  class RK,V,F step;
  class A,GD,VD gate;`;

const agents = (lang: Lang) =>
  lang === "tr"
    ? `flowchart TD
  S(["Soru"]) --> P["🧭 Planner — soruyu alt-sorulara böler"]
  P --> M["🔍 Moderator — eksik açıları ekler (STORM)"]
  M --> A{"👤 Onay Kapısı"}
  A -->|"kullanıcı düzenler / onaylar"| R["📚 Researcher — paralel fan-out + sorgu genişletme"]
  R --> RK["⚖️ Ranker — çok-sinyalli skor + filtre"]
  RK --> G["🕳️ Gap Analizi — eksik açıları arar"]
  G --> GD{"eksik kaldı mı?"}
  GD -->|"evet → yeni tur"| R
  GD -->|"hayır"| SY["✍️ Synthesizer — atıflı raporu yazar (akışlı, çoklu-dil paralel)"]
  SY --> V["🛡️ Verifier — atıf bağlantılarını doğrular"]
  V --> VD{"kanıt yeterli mi?"}
  VD -->|"kanıtsız iddia"| SY
  VD -->|"temiz"| F["✅ Finalizer — paketler + dışa aktarır"]
  F --> E(["Atıflı Rapor"])
${AGENT_CLASSDEFS}`
    : `flowchart TD
  S(["Question"]) --> P["🧭 Planner — splits the question into sub-questions"]
  P --> M["🔍 Moderator — adds missing angles (STORM)"]
  M --> A{"👤 Approval Gate"}
  A -->|"user edits / approves"| R["📚 Researcher — parallel fan-out + query expansion"]
  R --> RK["⚖️ Ranker — multi-signal score + filter"]
  RK --> G["🕳️ Gap Analysis — looks for missing angles"]
  G --> GD{"anything missing?"}
  GD -->|"yes → new round"| R
  GD -->|"no"| SY["✍️ Synthesizer — writes the cited report (streaming, multi-language parallel)"]
  SY --> V["🛡️ Verifier — re-checks citation links"]
  V --> VD{"evidence sufficient?"}
  VD -->|"unsupported claim"| SY
  VD -->|"clean"| F["✅ Finalizer — packages + exports"]
  F --> E(["Cited Report"])
${AGENT_CLASSDEFS}`;

const retrieval = (lang: Lang) =>
  lang === "tr"
    ? `flowchart TD
  Q["Alt-soru"] --> QE["Sorgu genişletme (TR↔EN + paraphrase)"]
  QE --> FO["Çoklu-kaynak fan-out"]
  FO --> W["🌐 Web: DuckDuckGo · Brave · Tavily"]
  FO --> AC["🎓 Akademik: arXiv · Crossref · OpenAlex · PubMed · Europe PMC · Semantic Scholar · DOAJ"]
  W --> DD["Tekilleştirme (DOI / arXiv / URL)"]
  AC --> DD
  DD --> FT["OA tam-metin: Unpaywall → PDF → pypdf"]
  FT --> EM["Yerel embedding: bge-m3"]
  EM --> HY["Hibrit arama: vektör + BM25 → RRF"]
  HY --> RR["Reranker (cross-encoder)"]
  RR --> SC["5-sinyal skor"]
  SC --> KP{"eşik üstü mü?"}
  KP -->|"evet"| KEEP["✓ Tutuldu + 'neden tutuldu'"]
  KP -->|"hayır"| DROP["✗ Elendi"]`
    : `flowchart TD
  Q["Sub-question"] --> QE["Query expansion (TR↔EN + paraphrase)"]
  QE --> FO["Multi-source fan-out"]
  FO --> W["🌐 Web: DuckDuckGo · Brave · Tavily"]
  FO --> AC["🎓 Academic: arXiv · Crossref · OpenAlex · PubMed · Europe PMC · Semantic Scholar · DOAJ"]
  W --> DD["Deduplication (DOI / arXiv / URL)"]
  AC --> DD
  DD --> FT["OA full-text: Unpaywall → PDF → pypdf"]
  FT --> EM["Local embedding: bge-m3"]
  EM --> HY["Hybrid search: vector + BM25 → RRF"]
  HY --> RR["Reranker (cross-encoder)"]
  RR --> SC["5-signal score"]
  SC --> KP{"above threshold?"}
  KP -->|"yes"| KEEP["✓ Kept + 'why kept'"]
  KP -->|"no"| DROP["✗ Dropped"]`;

const scoring = (lang: Lang) =>
  lang === "tr"
    ? `flowchart LR
  REL["İlgi · 0.40 (cross-encoder)"] --> SUM((("Final Skor")))
  AUT["Otorite · 0.15 (venue/domain)"] --> SUM
  REC["Güncellik · 0.15 (zaman-azalımı)"] --> SUM
  CIT["Atıf etkisi · 0.15 (log atıf)"] --> SUM
  EVD["Kanıt türü · 0.15 (RCT>hakemli>preprint)"] --> SUM
  SUM --> MS["Eşleşme skoru 0–100 + eşik filtresi"]`
    : `flowchart LR
  REL["Relevance · 0.40 (cross-encoder)"] --> SUM((("Final Score")))
  AUT["Authority · 0.15 (venue/domain)"] --> SUM
  REC["Recency · 0.15 (time-decay)"] --> SUM
  CIT["Citation impact · 0.15 (log citations)"] --> SUM
  EVD["Evidence type · 0.15 (RCT>peer-reviewed>preprint)"] --> SUM
  SUM --> MS["Match score 0–100 + threshold filter"]`;

const architecture = (lang: Lang) =>
  lang === "tr"
    ? `flowchart TB
  subgraph FE["Frontend — React 19 · Vite · Tailwind"]
    UI["AgentTrace · Konu Grafiği · Araştırma İzi · Canlı Konsol · Kaynak Kartları · Rapor · Dışa Aktarma"]
  end
  subgraph BE["Backend — Python · FastAPI"]
    API["REST + SSE"]
    LG["LangGraph + SQLite checkpoint"]
    LLM["LiteLLM (bulut · yerel Ollama · kendi sunucun) — şifreli anahtar kasası"]
    EMB["fastembed: bge-m3 + reranker"]
    SRC["13 kaynak sağlayıcı"]
  end
  subgraph DATA["Tek dosya: SQLite"]
    REL[("İlişkisel")]
    VEC[("sqlite-vec")]
    FTS[("FTS5")]
  end
  UI <-->|"/api + SSE"| API
  API --> LG
  LG --> LLM
  LG --> SRC
  LG --> EMB
  LG <--> DATA`
    : `flowchart TB
  subgraph FE["Frontend — React 19 · Vite · Tailwind"]
    UI["AgentTrace · Topic Graph · Research Trail · Live Console · Source Cards · Report · Export"]
  end
  subgraph BE["Backend — Python · FastAPI"]
    API["REST + SSE"]
    LG["LangGraph + SQLite checkpoint"]
    LLM["LiteLLM (cloud · local Ollama · your own server) — encrypted key vault"]
    EMB["fastembed: bge-m3 + reranker"]
    SRC["13 source providers"]
  end
  subgraph DATA["Single file: SQLite"]
    REL[("Relational")]
    VEC[("sqlite-vec")]
    FTS[("FTS5")]
  end
  UI <-->|"/api + SSE"| API
  API --> LG
  LG --> LLM
  LG --> SRC
  LG --> EMB
  LG <--> DATA`;

type Feature = { icon: LucideIcon; titleKey: string; descKey: string };

const FEATURES: Feature[] = [
  { icon: Gauge, titleKey: "about.feat.depth.title", descKey: "about.feat.depth.desc" },
  { icon: UserCheck, titleKey: "about.feat.hitl.title", descKey: "about.feat.hitl.desc" },
  { icon: Repeat, titleKey: "about.feat.gap.title", descKey: "about.feat.gap.desc" },
  { icon: Snowflake, titleKey: "about.feat.snowball.title", descKey: "about.feat.snowball.desc" },
  { icon: Languages, titleKey: "about.feat.bilingual.title", descKey: "about.feat.bilingual.desc" },
  { icon: Languages, titleKey: "about.feat.multilang.title", descKey: "about.feat.multilang.desc" },
  { icon: Eye, titleKey: "about.feat.transparent.title", descKey: "about.feat.transparent.desc" },
  { icon: BadgeCheck, titleKey: "about.feat.verify.title", descKey: "about.feat.verify.desc" },
  { icon: Scale, titleKey: "about.feat.disagreement.title", descKey: "about.feat.disagreement.desc" },
  { icon: Globe, titleKey: "about.feat.diversity.title", descKey: "about.feat.diversity.desc" },
  { icon: Route, titleKey: "about.feat.trail.title", descKey: "about.feat.trail.desc" },
  { icon: Sparkles, titleKey: "about.feat.ask.title", descKey: "about.feat.ask.desc" },
  { icon: TerminalSquare, titleKey: "about.feat.console.title", descKey: "about.feat.console.desc" },
  { icon: Cpu, titleKey: "about.feat.hybrid.title", descKey: "about.feat.hybrid.desc" },
  { icon: Boxes, titleKey: "about.feat.embedding.title", descKey: "about.feat.embedding.desc" },
  { icon: Download, titleKey: "about.feat.export.title", descKey: "about.feat.export.desc" },
];

function DiagramCard({
  title,
  caption,
  chart,
  id,
  extra,
}: {
  title: string;
  caption: string;
  chart: string;
  id: string;
  extra?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{caption}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <MermaidDiagram chart={chart} id={id} />
        {extra}
      </CardContent>
    </Card>
  );
}

/* ── Shape/colour legend for the agent graph ──────────────────────────────
   The swatch fills/borders mirror the Mermaid `classDef`s in AGENT_CLASSDEFS
   so a reader can map a colour in the diagram straight to a category here. */
type SwatchKind = "agent" | "step" | "gate" | "io";

const SWATCH_STYLE: Record<SwatchKind, { bg: string; border: string }> = {
  agent: { bg: "#1e1b4b", border: "#5B4BE6" },
  step: { bg: "#0f1b2d", border: "#3b82f6" },
  gate: { bg: "#1c1406", border: "#f59e0b" },
  io: { bg: "#0e1013", border: "#64748b" },
};

const AGENT_LEGEND: Record<Lang, { kind: SwatchKind; title: string; desc: string }[]> = {
  tr: [
    {
      kind: "agent",
      title: "AI Ajanı",
      desc: "LLM ile muhakeme eden adım — Planner · Moderator · Researcher · Gap Analizi · Synthesizer",
    },
    {
      kind: "step",
      title: "Deterministik adım",
      desc: "LLM kullanmaz; kural/ML ile çalışır — Ranker · Verifier · Finalizer",
    },
    {
      kind: "gate",
      title: "Karar / kapı",
      desc: "Dallanma noktası ya da insan onayı (HITL)",
    },
    { kind: "io", title: "Giriş / Çıkış", desc: "Sürecin başlangıcı ve sonucu" },
  ],
  en: [
    {
      kind: "agent",
      title: "AI Agent",
      desc: "A step that reasons with an LLM — Planner · Moderator · Researcher · Gap Analysis · Synthesizer",
    },
    {
      kind: "step",
      title: "Deterministic step",
      desc: "No LLM; rule/ML based — Ranker · Verifier · Finalizer",
    },
    {
      kind: "gate",
      title: "Decision / gate",
      desc: "A branch point or human approval (HITL)",
    },
    { kind: "io", title: "Input / Output", desc: "Start and result of the flow" },
  ],
};

function ShapeSwatch({ kind }: { kind: SwatchKind }) {
  const s = SWATCH_STYLE[kind];
  // gate → rotated square (diamond), io → pill, agent/step → rounded square.
  const shape =
    kind === "gate"
      ? "h-3 w-3 rotate-45 rounded-[2px]"
      : kind === "io"
        ? "h-3 w-5 rounded-full"
        : "h-3.5 w-3.5 rounded-[3px]";
  return (
    <span className="flex h-4 w-5 shrink-0 items-center justify-center">
      <span
        className={cn("inline-block border", shape)}
        style={{ backgroundColor: s.bg, borderColor: s.border }}
        aria-hidden
      />
    </span>
  );
}

function AgentLegend({ lang }: { lang: Lang }) {
  return (
    <div className="rounded-[var(--radius)] border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
      <p className="mb-2 text-xs font-semibold text-[var(--color-fg)]">
        {lang === "tr" ? "Şekil rehberi" : "Shape guide"}
      </p>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {AGENT_LEGEND[lang].map((it) => (
          <li key={it.title} className="flex items-start gap-2">
            <span className="mt-0.5">
              <ShapeSwatch kind={it.kind} />
            </span>
            <span className="min-w-0 text-xs leading-snug">
              <span className="font-medium text-[var(--color-fg)]">{it.title}</span>
              <span className="text-[var(--color-muted)]"> — {it.desc}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type TabId =
  | "overview"
  | "agents"
  | "retrieval"
  | "scoring"
  | "architecture"
  | "features"
  | "contribute";

const TABS: { id: TabId; labelKey: string }[] = [
  { id: "overview", labelKey: "about.tab.overview" },
  { id: "agents", labelKey: "about.tab.agents" },
  { id: "retrieval", labelKey: "about.tab.retrieval" },
  { id: "scoring", labelKey: "about.tab.scoring" },
  { id: "architecture", labelKey: "about.tab.architecture" },
  { id: "features", labelKey: "about.tab.features" },
  { id: "contribute", labelKey: "about.tab.contribute" },
];

export function About() {
  const { t, lang } = useLang();
  const [tab, setTab] = useState<TabId>("overview");

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Compact header — stays visible above the tab bar */}
      <div className="mb-5">
        <div className="mb-2 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--color-accent)] text-[var(--color-accent-fg)]">
            <BookOpen size={18} />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-[var(--color-fg)]">
            {t("about.title")}
          </h1>
        </div>
        <p className="max-w-2xl text-sm leading-relaxed text-[var(--color-muted)]">
          {t("about.intro")}
        </p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabId)}>
        {/* Horizontal, scrollable-on-overflow tab bar with accent pill/underline */}
        <div
          role="tablist"
          className="mb-5 flex gap-1 overflow-x-auto border-b border-[var(--color-border)] pb-px"
        >
          {TABS.map((tb) => {
            const active = tab === tb.id;
            return (
              <button
                key={tb.id}
                role="tab"
                type="button"
                aria-selected={active}
                onClick={() => setTab(tb.id)}
                className={cn(
                  "relative whitespace-nowrap rounded-t-[var(--radius)] px-3 py-2 text-xs font-medium transition-colors",
                  active
                    ? "text-[var(--color-accent)]"
                    : "text-[var(--color-muted)] hover:text-[var(--color-fg)]",
                )}
              >
                {t(tb.labelKey)}
                <span
                  className={cn(
                    "absolute inset-x-1.5 -bottom-px h-0.5 rounded-full transition-colors",
                    active ? "bg-[var(--color-accent)]" : "bg-transparent",
                  )}
                />
              </button>
            );
          })}
        </div>

        {/* Only the active panel mounts → its MermaidDiagram renders on switch */}
        <TabsContent value="overview" className="space-y-4">
          <DiagramCard
            id="lifecycle"
            title={t("about.lifecycle.title")}
            caption={t("about.lifecycle.caption")}
            chart={lifecycle(lang)}
          />
        </TabsContent>

        <TabsContent value="agents">
          <DiagramCard
            id="agents"
            title={t("about.agents.title")}
            caption={t("about.agents.caption")}
            chart={agents(lang)}
            extra={<AgentLegend lang={lang} />}
          />
        </TabsContent>

        <TabsContent value="retrieval">
          <DiagramCard
            id="retrieval"
            title={t("about.retrieval.title")}
            caption={t("about.retrieval.caption")}
            chart={retrieval(lang)}
          />
        </TabsContent>

        <TabsContent value="scoring">
          <DiagramCard
            id="scoring"
            title={t("about.scoring.title")}
            caption={t("about.scoring.caption")}
            chart={scoring(lang)}
            extra={
              <p className="rounded-[var(--radius)] border border-[color-mix(in_srgb,var(--color-accent)_35%,transparent)] bg-[var(--color-accent-soft)] px-3 py-2 font-mono text-[11px] leading-relaxed text-[var(--color-accent)]">
                {t("about.scoring.formula")}
              </p>
            }
          />
        </TabsContent>

        <TabsContent value="architecture">
          <DiagramCard
            id="architecture"
            title={t("about.architecture.title")}
            caption={t("about.architecture.caption")}
            chart={architecture(lang)}
          />
        </TabsContent>

        <TabsContent value="features">
          <Card>
            <CardHeader>
              <CardTitle>{t("about.features.title")}</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {FEATURES.map((f) => (
                <div
                  key={f.titleKey}
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3"
                >
                  <f.icon size={18} className="mb-2 text-[var(--color-accent)]" />
                  <p className="text-sm font-medium text-[var(--color-fg)]">
                    {t(f.titleKey)}
                  </p>
                  <p className="mt-0.5 text-xs leading-snug text-[var(--color-muted)]">
                    {t(f.descKey)}
                  </p>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="contribute">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitPullRequest size={15} /> {t("about.contribute.title")}
              </CardTitle>
              <CardDescription>{t("about.contribute.intro")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ContribRow
                icon={Layers}
                title={t("about.contribute.stack.title")}
                desc={t("about.contribute.stack.desc")}
              />
              <ContribRow
                icon={Boxes}
                title={t("about.contribute.layout.title")}
                desc={t("about.contribute.layout.desc")}
                mono
              />
              <ContribRow
                icon={PlayCircle}
                title={t("about.contribute.dev.title")}
                desc={t("about.contribute.dev.desc")}
                mono
              />
              <ContribRow
                icon={FlaskConical}
                title={t("about.contribute.tests.title")}
                desc={t("about.contribute.tests.desc")}
                mono
              />

              <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
                <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-[var(--color-fg)]">
                  <Lightbulb size={15} className="text-[var(--color-accent)]" />
                  {t("about.contribute.ideas.title")}
                </p>
                <ul className="list-disc space-y-1 pl-5 text-xs leading-snug text-[var(--color-muted)]">
                  <li>{t("about.contribute.idea1")}</li>
                  <li>{t("about.contribute.idea2")}</li>
                  <li>{t("about.contribute.idea3")}</li>
                </ul>
              </div>

              <p className="text-xs text-[var(--color-faint)]">
                {t("about.openSource")}
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ContribRow({
  icon: Icon,
  title,
  desc,
  mono,
}: {
  icon: LucideIcon;
  title: string;
  desc: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 shrink-0 text-[var(--color-accent)]">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-medium text-[var(--color-fg)]">{title}</p>
        <p
          className={
            mono
              ? "mt-0.5 break-words font-mono text-[11px] leading-snug text-[var(--color-muted)]"
              : "mt-0.5 text-xs leading-snug text-[var(--color-muted)]"
          }
        >
          {desc}
        </p>
      </div>
    </div>
  );
}
