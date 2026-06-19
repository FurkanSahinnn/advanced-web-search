import { useMemo } from "react";
import { Globe, AlertTriangle } from "lucide-react";
import type { SourceOut } from "../lib/types";
import { useLang } from "../lib/i18n";
import { cn } from "../lib/cn";

// Registrable-domain heuristic. A full public-suffix list is overkill for a
// diversity indicator, so we collapse to eTLD+1 using a small set of common
// multi-label suffixes (co.uk, com.tr, …); everything else collapses to the
// last two labels. Subdomains (news.bbc.co.uk) therefore fold into one domain
// (bbc.co.uk), which is what an echo-chamber check wants.
const MULTI_TLDS = new Set([
  "co.uk", "ac.uk", "gov.uk", "org.uk", "com.au", "net.au", "org.au",
  "co.jp", "co.kr", "com.tr", "edu.tr", "gov.tr", "org.tr", "com.br",
  "co.in", "co.nz", "com.cn", "com.mx", "co.za", "com.sg", "com.hk",
]);

// Aggregator domains shared by many distinct publishers/providers — counting
// them as one "domain" would understate diversity, so DOI/academic sources are
// bucketed by provider instead (arxiv vs crossref vs openalex stay distinct).
// Entries are eTLD+1 (registrable) form, since registrableDomain() runs first
// (e.g. dx.doi.org -> doi.org, ncbi.nlm.nih.gov -> nih.gov).
const AGGREGATOR_HOSTS = new Set([
  "doi.org", "semanticscholar.org", "openalex.org", "europepmc.org", "nih.gov",
]);

function registrableDomain(url: string | null | undefined): string {
  if (!url) return "";
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    const m = url.toLowerCase().match(/^(?:https?:\/\/)?([^/?#]+)/);
    host = m ? m[1] : "";
  }
  host = host.replace(/^www\./, "");
  if (!host) return "";
  const labels = host.split(".");
  if (labels.length <= 2) return host;
  const lastTwo = labels.slice(-2).join(".");
  return MULTI_TLDS.has(lastTwo) ? labels.slice(-3).join(".") : lastTwo;
}

function bucketOf(s: SourceOut): string {
  const dom = registrableDomain(s.url);
  if (!dom || AGGREGATOR_HOSTS.has(dom) || (s.kind && s.kind !== "web")) {
    return s.provider || dom || s.kind || "?";
  }
  return dom;
}

// Distinct, readable segment colors for the proportion bar (theme-agnostic so
// the buckets stay visually separable on either light or dark surfaces).
const SEGMENT_COLORS = [
  "var(--color-accent)", "#22a06b", "#d4a72c", "#6b8afd", "#c2618e", "#5cb1c4",
];
const OTHER_COLOR = "var(--color-faint)";

interface Diversity {
  total: number;
  distinct: number;
  topShare: number;
  topBucket: string;
  echo: boolean;
  segments: { bucket: string; count: number; color: string }[];
}

function computeDiversity(sources: SourceOut[]): Diversity | null {
  // The evidence actually used: kept sources (unscored streaming rows count as
  // kept candidates). Diversity of dropped sources is not informative.
  const kept = sources.filter((s) => s.score?.kept ?? true);
  const total = kept.length;
  if (total < 2) return null;

  const counts = new Map<string, number>();
  for (const s of kept) {
    const b = bucketOf(s);
    counts.set(b, (counts.get(b) ?? 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const distinct = sorted.length;
  const [topBucket, topCount] = sorted[0];
  const topShare = topCount / total;
  // Echo-chamber: with enough sources, a single domain dominating the evidence.
  const echo = total >= 4 && topShare >= 0.5;

  const TOP_N = 6;
  const segments = sorted.slice(0, TOP_N).map(([bucket, count], i) => ({
    bucket,
    count,
    color: SEGMENT_COLORS[i % SEGMENT_COLORS.length],
  }));
  const shown = segments.reduce((a, s) => a + s.count, 0);
  if (total - shown > 0) {
    segments.push({ bucket: "__other__", count: total - shown, color: OTHER_COLOR });
  }
  return { total, distinct, topShare, topBucket, echo, segments };
}

/**
 * Compact source-diversity strip for the sources pane: distinct-domain count,
 * a proportion bar across the top domains, and an echo-chamber warning when one
 * domain dominates the evidence. Computed entirely client-side from the kept
 * sources — no backend round-trip. Renders nothing for <2 sources.
 */
export function SourceDiversity({
  sources,
  className,
}: {
  sources: SourceOut[];
  className?: string;
}) {
  const { t } = useLang();
  const d = useMemo(() => computeDiversity(sources), [sources]);
  if (!d) return null;

  const topPct = Math.round(d.topShare * 100);
  const level = d.echo ? "echo" : d.topShare >= 0.35 ? "mid" : "diverse";
  const levelColor =
    level === "echo"
      ? "var(--color-danger)"
      : level === "mid"
        ? "var(--color-fg)"
        : "var(--color-good)";

  return (
    <div
      className={cn(
        "border-b border-[var(--color-border)] px-3 py-2",
        className,
      )}
    >
      <div className="flex items-center gap-1.5 text-[11px]">
        <Globe size={12} style={{ color: levelColor }} className="shrink-0" />
        <span className="font-medium text-[var(--color-muted)]">
          {t("diversity.title")}
        </span>
        <span className="text-[var(--color-faint)]">
          {d.distinct} {t("diversity.domains")} · {d.total} {t("diversity.sources")}
        </span>
        <span className="ml-auto truncate text-[var(--color-faint)]" title={d.topBucket}>
          {t("diversity.top")} {topPct}% {bucketLabel(d.topBucket, t)}
        </span>
      </div>

      {/* Proportion bar across the top domains. */}
      <div
        className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]"
        role="img"
        aria-label={`${t("diversity.title")}: ${d.distinct} ${t("diversity.domains")}, ${t("diversity.top")} ${topPct}% ${bucketLabel(d.topBucket, t)}`}
      >
        {d.segments.map((s) => (
          <div
            key={s.bucket}
            style={{ width: `${(s.count / d.total) * 100}%`, background: s.color }}
            title={`${bucketLabel(s.bucket, t)} · ${s.count}`}
          />
        ))}
      </div>

      {d.echo && (
        <div className="mt-1.5 flex items-start gap-1.5 text-[10px] text-[var(--color-danger)]">
          <AlertTriangle size={12} className="mt-px shrink-0" />
          <span>
            <span className="font-semibold">{t("diversity.echo")}:</span>{" "}
            {topPct}% {t("diversity.echoFrom")} {bucketLabel(d.topBucket, t)}
          </span>
        </div>
      )}
    </div>
  );
}

function bucketLabel(bucket: string, t: (k: string) => string): string {
  return bucket === "__other__" ? t("diversity.other") : bucket;
}
