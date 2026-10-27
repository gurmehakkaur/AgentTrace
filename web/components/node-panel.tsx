"use client";

import Link from "next/link";
import { useState } from "react";
import { Checks } from "@/components/checks";
import { TileCell } from "@/components/experiment-view";
import { Inspector } from "@/components/inspector";
import { nodeRuns } from "@/lib/runs";
import { JsonBlock } from "@/components/json-block";
import type { GNode } from "@/lib/graph";
import type { Candidate, Experiment, RcaReport, Run } from "@/lib/types";
import { verdictFor } from "@/lib/verdict";


/** What the selected node is. Everything on the line opens here: the request, an agent, a change, the
 * runs that followed it, and the answer. */
export function NodePanel({
  node, run, report, experiments, mode, runHref, experimentHref, onForkBranch, canFork = true,
}: {
  onForkBranch?: (experimentId: string, nodeRun: number) => void; // fork one of a fork's own runs
  canFork?: boolean; // false for imported runs: they can be read, not forked
  node: GNode | null;
  run: Run;
  report: RcaReport | null;
  experiments: Experiment[];
  mode: "app" | "demo";
  runHref: (runId: string) => string;
  experimentHref: (id: string) => string | null;
}) {
  if (!node) {
    return (
      <section className="card p-5 text-muted" aria-live="polite">
        Select a node on the line to see what it is, what it received and what it said.
      </section>
    );
  }
  if (node.draft) {
    return (
      <section className="card p-5" aria-live="polite" aria-label="Details: new fork">
        <h3 className="font-serif text-xl">Your new fork</h3>
        <p className="mt-1 max-w-prose text-muted">
          This line is not running yet. Change a value in the editor beside it, then click Fork and run. This line becomes real and fills in as the runs finish.
        </p>
      </section>
    );
  }
  const exp = node.experiment ? experiments.find((e) => e.id === node.experiment) : undefined;
  return (
    <section className="card p-5" aria-live="polite" aria-label={`Details: ${node.label}`}>
      {node.kind === "start" && <Request run={run} />}
      {node.kind === "agent" && <AgentDetail node={node} run={run} report={report} mode={mode} canFork={canFork} />}
      {node.kind === "edited" && exp && <Edited exp={exp} node={node} href={experimentHref(exp.id)} />}
      {node.kind === "live" && exp && <Live exp={exp} node={node} runHref={runHref} onFork={mode === "app" && canFork && onForkBranch ? () => onForkBranch(exp.id, node.nodeRun ?? 0) : undefined} />}
      {node.kind === "result" && !exp && <Answer run={run} />}
      {node.kind === "result" && exp && <Branch exp={exp} runHref={runHref} href={experimentHref(exp.id)} />}
    </section>
  );
}

function Request({ run }: { run: Run }) {
  const first = run.steps.find((s) => s.idx === Math.min(...run.steps.map((x) => x.idx)));
  const messages = (first?.input as { messages?: { content?: unknown }[] } | null)?.messages;
  const text = typeof messages?.[0]?.content === "string" ? messages[0].content : null;
  return (
    <>
      <h3 className="font-serif text-xl">The request</h3>
      <p className="mt-1 max-w-prose text-muted">This is what the first agent was asked to do.</p>
      {text && <p className="mt-3 rounded-lg bg-tile p-3">{text}</p>}
    </>
  );
}

function AgentDetail({
  node, run, report, mode, canFork,
}: { node: GNode; run: Run; report: RcaReport | null; mode: "app" | "demo"; canFork: boolean }) {
  const steps = run.steps.filter((s) => s.node_run_idx === node.nodeRun).sort((a, b) => a.idx - b.idx);
  const [pick, setPick] = useState(0);
  const step = steps[Math.min(pick, steps.length - 1)];
  const cause: Candidate | undefined = node.mark?.kind === "cause" ? report?.candidates.find((c) => c.node_run_idx === node.nodeRun) : undefined;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-serif text-xl capitalize">{node.label}</h3>
          <p className="text-muted">{where(run, node.nodeRun)}</p>
        </div>
        {mode === "app" && !canFork && <span className="rounded-full border border-line px-3 py-1 text-muted">View only</span>}
      </div>
      {cause && (
        <p className="rounded-lg border border-bad/30 bg-bad-tint p-3 text-ink">
          <span className="font-medium text-bad">Likely cause ({Math.round(cause.confidence * 100)}% sure). </span>
          {cause.hypothesis}
        </p>
      )}
      {steps.length > 1 && (
        <div role="group" aria-label="Steps of this agent" className="flex flex-wrap gap-2">
          {steps.map((s, i) => (
            <button
              key={s.idx}
              type="button"
              onClick={() => setPick(i)}
              aria-pressed={step.idx === s.idx}
              className={`rounded-lg border px-3 py-1.5 ${step.idx === s.idx ? "border-ink bg-ink text-frame" : "border-line hover:bg-tile"}`}
            >
              {s.kind === "tool" ? `Tool: ${s.tool_name ?? "call"}` : "Model call"}
            </button>
          ))}
        </div>
      )}
      <Inspector step={step} steps={run.steps} />
    </div>
  );
}

/** "Agent 2 of 4. It started after the planner finished." */
function where(run: Run, nodeRun?: number): string {
  const turns = nodeRuns(run.steps);
  const i = turns.findIndex((t) => t.idx === nodeRun);
  if (i < 0) return "";
  const calls = turns[i].steps.length;
  return `Agent ${i + 1} of ${turns.length}. ${i === 0 ? "It ran first." : `It started after the ${turns[i - 1].agent} finished.`} ${calls} step${calls === 1 ? "" : "s"}.`;
}

function Edited({ exp, node, href }: { exp: Experiment; node: GNode; href: string | null }) {
  return (
    <>
      <h3 className="font-serif text-xl"><span className="capitalize">{node.label}</span>, with your change</h3>
      <p className="mt-1 max-w-prose text-muted">
        This fork replaced what the {node.label} wrote with the value below. Everything before it replays exactly from the
        recording. Everything after it runs live.
      </p>
      {node.change && node.change.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-1.5">
          {node.change.map((l) => (
            <li key={l} className="rounded-lg bg-tile px-3 py-2"><code className="font-mono text-[0.8125rem] [overflow-wrap:anywhere]">{l}</code></li>
          ))}
        </ul>
      ) : (
        <div className="mt-3"><JsonBlock label="The value it was given instead" value={exp.edit_patch} /></div>
      )}
      {href && <Link href={href} className="mt-3 inline-block underline underline-offset-4">Open the full experiment</Link>}
    </>
  );
}

function Live({ exp, node, runHref, onFork }: { exp: Experiment; node: GNode; runHref: (id: string) => string; onFork?: () => void }) {
  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
      <h3 className="font-serif text-xl"><span className="capitalize">{node.label}</span>, run again live</h3>
      {onFork && <button type="button" className="btn btn-primary" onClick={onFork}>Fork here</button>}
      </div>
      <p className="mt-1 max-w-prose text-muted">
        In this fork the {node.label} ran again {exp.n} times with the change and {exp.n} times without it, against Claude.
        Live runs are sampled, so they can differ from each other. Open any run below to see exactly what happened in it.
      </p>
      <Tiles exp={exp} runHref={runHref} />
    </>
  );
}

function Branch({ exp, runHref, href }: { exp: Experiment; runHref: (id: string) => string; href: string | null }) {
  const verdict = ["queued", "running"].includes(exp.status) ? null : verdictFor(exp.control, exp.treatment, exp.stats.fisher_p);
  return (
    <>
      <h3 className={`font-serif text-xl ${verdict?.tone === "good" ? "text-good" : verdict?.tone === "bad" ? "text-bad" : ""}`}>
        {verdict ? verdict.text : "This fork is still running"}
      </h3>
      <p className="mt-1 text-muted">
        Without the change {exp.control.pass} of {exp.control.total} runs were right. With it, {exp.treatment.pass} of {exp.treatment.total}.
        {exp.stats.fisher_p !== null && ` Fisher exact p ${exp.stats.fisher_p < 0.001 ? "< 0.001" : `≈ ${exp.stats.fisher_p.toFixed(3)}`}, ${exp.stats.label}.`}
      </p>
      <Tiles exp={exp} runHref={runHref} />
      {href && <Link href={href} className="mt-3 inline-block underline underline-offset-4">Open the full experiment</Link>}
    </>
  );
}

function Tiles({ exp, runHref }: { exp: Experiment; runHref: (id: string) => string }) {
  return (
    <div className="mt-4 flex flex-col gap-3">
      {(["control", "treatment"] as const).map((arm) => (
        <div key={arm} className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="w-40 shrink-0 text-muted">{arm === "control" ? "Without the change" : "With the change"}</span>
          <ul className="flex flex-wrap gap-1.5">
            {exp.tiles.filter((t) => t.arm === arm).map((t) => (
              <li key={`${t.arm}-${t.i}`}><TileCell tile={t} runHref={runHref} /></li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Answer({ run }: { run: Run }) {
  const got = run.oracle_detail?.footer?.open_tickets;
  const want = run.oracle_detail?.truth?.open_tickets;
  const wrong = run.outcome === "fail" || run.outcome === "error";
  return (
    <>
      <h3 className={`font-serif text-xl ${wrong ? "text-bad" : "text-good"}`}>{wrong ? "The answer was wrong" : "The answer was right"}</h3>
      {got !== undefined && want !== undefined && (
        <p className="mt-1 text-muted">The brief reported {got} open tickets. The real number is {want}. A check in code compared them, not an AI.</p>
      )}
      {run.oracle_detail && <div className="mt-3"><Checks detail={run.oracle_detail} /></div>}
    </>
  );
}
