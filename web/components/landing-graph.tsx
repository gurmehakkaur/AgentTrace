"use client";

import { useMemo, useState } from "react";
import { FlowGraph } from "@/components/flow-graph";
import { NodePanel } from "@/components/node-panel";
import { buildGraph } from "@/lib/graph";
import type { Demo } from "@/lib/demo";
import { marksFromReport } from "@/lib/story";

/** The saved demo run as the landing page's picture. Every node can be selected, as in the real app. */
export function LandingGraph({ demo }: { demo: Demo }) {
  const marks = useMemo(() => marksFromReport(demo.rca), [demo.rca]);
  const [selected, setSelected] = useState<string | null>(null);
  const got = demo.run.oracle_detail?.footer?.open_tickets;
  const want = demo.run.oracle_detail?.truth?.open_tickets;
  const resultText = got !== undefined && want !== undefined ? `${got} open tickets, not ${want}` : undefined;
  const node = useMemo(
    () => (selected ? buildGraph(demo.run.steps, { marks, experiments: demo.experiments, outcome: demo.run.outcome, resultText }).nodes.find((n) => n.id === selected) ?? null : null),
    [selected, demo, marks, resultText],
  );
  return (
    <div className="flex flex-col gap-3">
      <FlowGraph
        steps={demo.run.steps} marks={marks} experiments={demo.experiments} outcome={demo.run.outcome} resultText={resultText}
        selected={selected} onSelect={(n) => setSelected((s) => (s === n.id ? null : n.id))}
      />
      <NodePanel
        node={node} run={demo.run} report={demo.rca} experiments={demo.experiments} mode="demo"
        runHref={(id) => `/demo/runs/${id}`} experimentHref={() => null}
      />
    </div>
  );
}
