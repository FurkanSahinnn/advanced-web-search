import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Position,
  type Edge,
  type Node,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { SubtopicOut } from "../lib/types";
import { cn } from "../lib/cn";

interface FlowData extends Record<string, unknown> {
  label: string;
  perspective: string | null;
  isRoot: boolean;
  status: string;
}

const COL_W = 280;
const ROW_H = 92;

// Tiered layout by depth: each depth is a column; nodes stack vertically.
function layout(
  rootQuery: string,
  tree: SubtopicOut[],
): { nodes: Node<FlowData>[]; edges: Edge[] } {
  const nodes: Node<FlowData>[] = [];
  const edges: Edge[] = [];

  const ROOT_ID = "root";
  nodes.push({
    id: ROOT_ID,
    type: "topic",
    position: { x: 0, y: 0 },
    data: { label: rootQuery, perspective: null, isRoot: true, status: "root" },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  });

  // group flattened nodes by depth
  const byDepth = new Map<number, SubtopicOut[]>();
  const walk = (nodesList: SubtopicOut[]) => {
    for (const n of nodesList) {
      const arr = byDepth.get(n.depth) ?? [];
      arr.push(n);
      byDepth.set(n.depth, arr);
      if (n.children?.length) walk(n.children);
    }
  };
  walk(tree);

  const yCursor = new Map<number, number>();
  const maxDepth = Math.max(0, ...[...byDepth.keys()]);

  // Center root vertically against the tallest column.
  const tallest = Math.max(1, ...[...byDepth.values()].map((a) => a.length));
  nodes[0].position = { x: 0, y: ((tallest - 1) * ROW_H) / 2 };

  for (let d = 0; d <= maxDepth; d++) {
    const list = byDepth.get(d) ?? [];
    list.sort((a, b) => a.ord - b.ord);
    list.forEach((st) => {
      const col = d + 1;
      const y = yCursor.get(d) ?? 0;
      yCursor.set(d, y + 1);
      nodes.push({
        id: String(st.id),
        type: "topic",
        position: { x: col * COL_W, y: y * ROW_H },
        data: {
          label: st.question,
          perspective: st.perspective ?? null,
          isRoot: false,
          status: st.status,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
      const parent = st.parent_id != null ? String(st.parent_id) : ROOT_ID;
      edges.push({
        id: `e-${parent}-${st.id}`,
        source: parent,
        target: String(st.id),
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed, color: "#353c45" },
      });
    });
  }

  return { nodes, edges };
}

function TopicNode({ data }: { data: FlowData }) {
  return (
    <div
      className={cn(
        "max-w-[248px] rounded-lg border px-3 py-2 text-xs shadow-sm",
        data.isRoot
          ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
          : "border-[var(--color-border-strong)] bg-[var(--color-elevated)]",
      )}
    >
      <p
        className={cn(
          "line-clamp-3 leading-snug",
          data.isRoot
            ? "font-semibold text-[var(--color-accent)]"
            : "text-[var(--color-fg)]",
        )}
      >
        {data.label}
      </p>
      {data.perspective && (
        <span className="mt-1.5 inline-block rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-0.5 text-[10px] text-[var(--color-muted)]">
          {data.perspective}
        </span>
      )}
    </div>
  );
}

const nodeTypes = { topic: TopicNode };

export function TopicGraph({
  rootQuery,
  subtopics,
  className,
}: {
  rootQuery: string;
  subtopics: SubtopicOut[];
  className?: string;
}) {
  const { nodes, edges } = useMemo(
    () => layout(rootQuery, subtopics),
    [rootQuery, subtopics],
  );

  return (
    <div className={cn("h-full w-full", className)}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.2}
        maxZoom={1.5}
      >
        <Background color="#262b32" gap={20} />
        <Controls
          showInteractive={false}
          className="!border-[var(--color-border)] !bg-[var(--color-surface)]"
        />
      </ReactFlow>
    </div>
  );
}
