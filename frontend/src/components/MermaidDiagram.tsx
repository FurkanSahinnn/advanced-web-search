import { useEffect, useId, useRef, useState } from "react";

type Props = {
  /** Mermaid diagram source. */
  chart: string;
  /** Optional stable id prefix (defaults to a generated one). */
  id?: string;
};

/**
 * Renders a Mermaid diagram. `mermaid` is imported DYNAMICALLY so it ships as
 * its own lazy chunk and never bloats the main app bundle. The library is
 * heavy (~hundreds of KB) and only needed on the About page.
 *
 * On render failure we degrade gracefully and show the raw chart source in a
 * <pre> so the page never breaks.
 */
export function MermaidDiagram({ chart, id }: Props) {
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const renderId = `mermaid-${id ?? reactId}`;
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;

        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "loose",
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
          themeVariables: {
            // Tuned to the Advanced Web Search dark theme (indigo #5B4BE6 accent).
            background: "#111316",
            primaryColor: "#15181c",
            primaryBorderColor: "#5B4BE6",
            primaryTextColor: "#e8ecf1",
            secondaryColor: "#1e1b4b",
            secondaryBorderColor: "#262b32",
            secondaryTextColor: "#e8ecf1",
            tertiaryColor: "#1a1e24",
            tertiaryBorderColor: "#353c45",
            tertiaryTextColor: "#e8ecf1",
            lineColor: "#353c45",
            textColor: "#e8ecf1",
            mainBkg: "#15181c",
            nodeBorder: "#5B4BE6",
            clusterBkg: "#0e1013",
            clusterBorder: "#262b32",
            titleColor: "#e8ecf1",
            edgeLabelBackground: "#111316",
            fontSize: "13px",
          },
          flowchart: {
            curve: "basis",
            htmlLabels: true,
            // Cap each SVG at its own natural width so it never upscales.
            useMaxWidth: true,
            padding: 8,
            nodeSpacing: 26,
            rankSpacing: 36,
          },
        });

        // Unique id per render avoids mermaid's internal cache collisions.
        const { svg } = await mermaid.render(
          `${renderId}-${Math.random().toString(36).slice(2, 8)}`,
          chart,
        );
        if (cancelled) return;
        setError(null);
        if (containerRef.current) {
          containerRef.current.innerHTML = svg;
          const svgEl = containerRef.current.querySelector("svg");
          if (svgEl) {
            // Pin the SVG to its OWN natural width as the upper bound. Mermaid
            // sizes nodes/text for this width; letting it grow past it (e.g.
            // stretching a sparse vertical flowchart to the full card) balloons
            // every node. Below that ceiling it stays fluid so it shrinks to
            // fit narrow screens, with height following the aspect ratio.
            const vb = svgEl.viewBox?.baseVal;
            const naturalWidth =
              vb && vb.width > 0
                ? vb.width
                : parseFloat(svgEl.getAttribute("width") || "0");
            svgEl.removeAttribute("width");
            svgEl.removeAttribute("height");
            svgEl.style.width = "100%";
            svgEl.style.height = "auto";
            if (naturalWidth > 0) {
              svgEl.style.maxWidth = `${Math.ceil(naturalWidth)}px`;
            }
          }
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chart, renderId]);

  if (error) {
    return (
      <div className="overflow-x-auto rounded-[var(--radius)] border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
        <p className="mb-2 text-[11px] text-[var(--color-danger)]">
          Diagram render failed: {error}
        </p>
        <pre className="whitespace-pre text-[11px] leading-snug text-[var(--color-muted)]">
          {chart}
        </pre>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius)] border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
      <div ref={containerRef} className="flex justify-center" />
    </div>
  );
}
