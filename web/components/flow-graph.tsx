"use client";

import { useMemo } from "react";
import { buildGraph, COL_W, type GEdge, type GNode, laneY, pos, type Tone } from "@/lib/graph";
import type { Mark } from "@/lib/story";
import type { Experiment, Step } from "@/lib/types";

const R = 22; // node radius
const TONE_TEXT: Record<Tone, string> = { neutral: "text-ink", good: "text-good", bad: "text-bad" };

/** The run as one continuous line, left to right, in the order things ran. Every fork opens a new line
 * below it that leaves the original where the change was made. Select a node to see what it is. */
export function FlowGraph({
  steps, marks, experiments = [], outcome, resultText, selected, onSelect, draft = null,
}: {
  draft?: { nodeRun: number; fromExperiment?: string | null } | null;
  steps: Step[];
  marks: Map<number, Mark>;
  experiments?: Experiment[];
  outcome?: string;
  resultText?: string;
  selected: string | null;
  onSelect: (node: GNode) => void;
}) {
  const graph = useMemo(() => buildGraph(steps, { marks, experiments, outcome, resultText, draft }), [steps, marks, experiments, outcome, resultText, draft]);
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);

  return (
    <div className="graph-scroll card overflow-x-auto" role="group" aria-label="The run as a line of agents. Select a node for details.">
      <div className="relative" style={{ width: graph.width, height: graph.height }}>
        <svg className="absolute inset-0" width={graph.width} height={graph.height} aria-hidden>
          <defs>
            <marker id="tip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
              <path d="M0 1 L10 5 L0 9 z" fill="#9d998e" />
            </marker>
          </defs>
          {graph.edges.map((e) => <Edge key={e.id} edge={e} byId={byId} tone={graph.lanes[e.lane].tone} />)}
        </svg>

        {graph.lanes.map((lane) => (
          <p
            key={lane.index}
            className={`absolute text-[0.8125rem] leading-snug text-muted ${lane.index === 0 ? "" : "w-[104px]"}`}
            style={lane.index === 0 ? { left: 36, top: laneY(0) - 62 } : { left: 16, top: laneY(lane.index) - 16 }}
          >
            <span className={`mr-2 inline-block h-2 w-2 rounded-full ${lane.index === 0 ? "bg-muted" : lane.tone === "good" ? "bg-good" : lane.tone === "bad" ? "bg-bad" : "bg-muted"}`} aria-hidden />
            {lane.label}
          </p>
        ))}

        {graph.nodes.map((n) => <Node key={n.id} node={n} selected={selected === n.id} onSelect={onSelect} />)}
      </div>
    </div>
  );
}

function Edge({ edge, byId, tone }: { edge: GEdge; byId: Map<string, GNode>; tone: Tone }) {
  const a = byId.get(edge.from);
  const b = byId.get(edge.to);
  if (!a || !b) return null;
  const p = pos(a);
  const q = pos(b);
  const stroke = edge.lane === 0 ? "#6b675f" : tone === "good" ? "#4fa874" : tone === "bad" ? "#c9695d" : "#9d998e";
  if (edge.kind === "spawn") {
    // A new line leaves at a junction on the line it was forked from, between the agent before the
    // change and the agent that was changed. It runs down to its own lane and turns toward that agent.
    // Forks that share a junction share the run down, and each turns off at its own lane.
    // Forks from different lines get slightly different runs down, so two of them never lie on top of each other.
    const jx = (p.x + q.x) / 2 + Math.min(a.lane * 8, 40);
    const r = 14;
    const d = `M ${jx} ${p.y} V ${q.y - r} Q ${jx} ${q.y} ${jx + r} ${q.y} H ${q.x - R - 1}`;
    return (
      <g>
        <path d={d} fill="none" stroke={stroke} strokeWidth={2} className="draw" style={{ ["--len" as string]: Math.abs(q.y - p.y) + Math.abs(q.x - jx) + 80 }} markerEnd="url(#tip)" />
        <circle cx={jx} cy={p.y} r={4} fill={stroke} />
      </g>
    );
  }
  return <line x1={p.x + R + 1} y1={p.y} x2={q.x - R - 1} y2={q.y} stroke={stroke} strokeWidth={2} className={edge.lane === 0 ? "" : "draw"} style={{ ["--len" as string]: COL_W }} markerEnd="url(#tip)" />;
}

function Node({ node: n, selected, onSelect }: { node: GNode; selected: boolean; onSelect: (n: GNode) => void }) {
  const { x, y } = pos(n);
  const ring =
    n.draft ? "border-dashed border-muted" : n.origin === "replayed" ? "border-line" : n.origin === "live" ? "border-muted" : n.mark?.kind === "cause" ? "border-bad" : n.mark?.kind === "carried" ? "border-warn" : n.kind === "edited" ? "border-dashed border-ink" : n.kind === "live" ? "border-muted" : "border-line";
  const fill = n.mark?.kind === "cause" ? "bg-bad-tint" : n.mark?.kind === "carried" ? "bg-warn-tint" : "bg-sheet";
  const label = n.kind === "result"
    ? <span className={`rounded-full border px-3 py-1 text-[0.9375rem] font-medium ${n.tone === "bad" ? "border-bad/40 bg-bad-tint text-bad" : n.tone === "good" ? "border-good/40 bg-good-tint text-good" : "border-line bg-tile text-ink"}`}>{n.label}</span>
    : <span className={`text-[0.9375rem] font-medium capitalize ${TONE_TEXT[n.tone]}`}>{n.label}</span>;

  return (
    <button
      type="button"
      onClick={() => onSelect(n)}
      aria-pressed={selected}
      aria-label={`${n.label}. ${n.sub}`}
      className={`arrive absolute flex w-[138px] flex-col items-center gap-1.5 text-center ${n.draft ? "opacity-70" : ""}`}
      style={{ left: x - 69, top: y - R }}
    >
      {n.kind === "result" ? (
        <span className="flex h-11 items-center">{label}</span>
      ) : n.kind === "start" ? (
        <span className={`mt-3.5 h-4 w-4 rounded-full border-2 bg-frame ${selected ? "border-accent" : "border-muted"}`} />
      ) : (
        <span className={`flex h-11 w-11 items-center justify-center rounded-full border-2 ${ring} ${fill} ${selected ? "ring-2 ring-accent ring-offset-2 ring-offset-sheet" : "hover:border-ink"}`}>
          <span className={`h-2.5 w-2.5 rounded-full ${n.kind === "edited" ? "bg-ink" : n.mark?.kind === "cause" ? "bg-bad" : n.mark?.kind === "carried" ? "bg-warn" : "bg-muted"}`} />
        </span>
      )}
      {n.kind !== "result" && label}
      {/* What the agent does (or what happened), then, if it matters, how it is involved in the mistake. */}
      <span className="line-clamp-3 max-w-[134px] text-[0.8125rem] leading-snug text-muted" title={n.sub}>{n.sub}</span>
      {n.mark?.kind === "cause" && (
        <span className="rounded-full border border-bad/40 bg-bad-tint px-2 py-0.5 text-[0.75rem] font-medium text-bad">
          Likely cause · {Math.round(n.mark.confidence * 100)}%
        </span>
      )}
      {n.mark?.kind === "carried" && (
        <span className="rounded-full border border-warn/40 bg-warn-tint px-2 py-0.5 text-[0.75rem] font-medium text-warn">Affected by it</span>
      )}
    </button>
  );
}
