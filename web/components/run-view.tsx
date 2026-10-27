"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { BenchmarkTable } from "@/components/benchmark-table";
import { Checks } from "@/components/checks";
import { DeleteRun } from "@/components/delete-run";
import { isFinished } from "@/components/experiment-view";
import { FlowGraph } from "@/components/flow-graph";
import { NodePanel } from "@/components/node-panel";
import { RcaPanel } from "@/components/rca-panel";
import { RcaView } from "@/components/rca-view";
import { TestFixPanel } from "@/components/test-fix-panel";
import { useApi } from "@/lib/api";
import { formatTime, formatTokens } from "@/lib/format";
import { headline } from "@/lib/checks";
import { buildGraph } from "@/lib/graph";
import { marksFromReport } from "@/lib/story";
import type { Experiment, RcaReport, Run, State } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

/** A run as a workbench. The answer and what was wrong with it, the line of agents with every fork as a branch,
 * and, under the line, whatever you select: what went in, what came out, and the editor to change it and fork.
 * `mode="demo"` is the public read-only view. */
export function RunView({
  run, mode = "app", report = null, experiments = [], titleLevel = 1, extra = null,
}: {
  run: Run; mode?: "app" | "demo"; report?: RcaReport | null; experiments?: Experiment[]; titleLevel?: 1 | 2; extra?: React.ReactNode;
}) {
  return mode === "app" ? <AppRun run={run} titleLevel={titleLevel} /> : (
    <RunBody run={run} mode="demo" report={report} experiments={experiments} titleLevel={titleLevel} extra={extra} />
  );
}

/** The signed-in run: its forks are read from the API, and polled while any is still running. */
function AppRun({ run, titleLevel }: { run: Run; titleLevel: 1 | 2 }) {
  const fork = useSearchParams().get("fork"); // the project timeline links here with a fork to show
  const [tick, setTick] = useState(0); // bumping it asks for the list again, right after a fork starts
  const state = useApiData<Experiment[]>(`/v1/runs/${run.id}/experiments?k=${tick}`, (list) => (list.some((e) => !isFinished(e)) ? 1500 : null));
  const experiments = state.status === "ok" ? state.data : [];
  const forksError = state.status === "error" ? state.message : null;
  return <RunBody run={run} mode="app" report={null} experiments={experiments} forksError={forksError} titleLevel={titleLevel} onForked={() => setTick((t) => t + 1)} initialSelected={fork ? `${fork}:end` : null} />;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function RunBody({
  run, mode, report, experiments, titleLevel, onForked, extra = null, initialSelected = null, forksError = null,
}: {
  initialSelected?: string | null;
  forksError?: string | null;
  run: Run; mode: "app" | "demo"; report: RcaReport | null; experiments: Experiment[]; titleLevel: 1 | 2;
  onForked?: (experimentId: string) => void; extra?: React.ReactNode;
}) {
  const Title = titleLevel === 1 ? "h1" : "h2";
  const agents = useMemo(() => new Map(run.steps.map((s) => [s.node_run_idx, s.agent])), [run.steps]);
  const [saved, setSaved] = useState<RcaReport | null>(null); // what the signed-in RCA panel loaded
  const known = report ?? saved;
  const marks = useMemo(() => marksFromReport(known), [known]);
  const [selected, setSelected] = useState<string | null>(initialSelected);
  const [suggest, setSuggest] = useState<{ nodeRun: number; patch: State; nonce: number } | null>(null); // "Test this fix" from the cause box
  const [dirty, setDirty] = useState(false); // the editor holds a change: the new line is drawn as it would be
  // When forking inside a fork, the fork starts from one real run of that fork, so the editor needs that run.
  const [base, setBase] = useState<{ experimentId: string; runId: string; nodeRun: number } | null>(null);
  const [loaded, setLoaded] = useState<{ id: string; run: Run } | null>(null);
  const baseRun = base && loaded?.id === base.runId ? loaded.run : null;
  const [forkNote, setForkNote] = useState<string | null>(null);
  const api = useApi();
  useEffect(() => {
    if (!base) return;
    let off = false;
    api<Run>(`/v1/runs/${base.runId}`)
      .then((r) => !off && setLoaded({ id: base.runId, run: r }))
      .catch(() => !off && setForkNote("Could not load that fork's run, so it cannot be forked from here."));
    return () => { off = true; };
  }, [base, api]);

  const failed = run.outcome === "fail" || run.outcome === "error";
  const got = run.oracle_detail?.footer?.open_tickets;
  const want = run.oracle_detail?.truth?.open_tickets;
  const resultText = got !== undefined && want !== undefined ? `${got} open tickets, not ${want}` : undefined;
  const canFork = mode === "app" && run.forkable !== false;

  const picked = selected ? buildGraph(run.steps, { marks, experiments, outcome: run.outcome, resultText }).nodes.find((n) => n.id === selected) ?? null : null;
  // What the editor is for: the agent selected on the original line, or an agent inside the fork that is being forked.
  const target = picked?.kind === "agent" ? { nodeRun: picked.nodeRun ?? 0, from: null as string | null }
    : base && picked?.experiment === base.experimentId ? { nodeRun: base.nodeRun, from: base.experimentId } : null;
  const draftRun = dirty && target ? target.nodeRun : null;
  const draftFrom = dirty && target ? target.from : null;
  const graph = useMemo(
    () => buildGraph(run.steps, { marks, experiments, outcome: run.outcome, resultText, draft: draftRun === null ? null : { nodeRun: draftRun, fromExperiment: draftFrom } }),
    [run.steps, run.outcome, marks, experiments, resultText, draftRun, draftFrom],
  );
  const node = selected ? graph.nodes.find((n) => n.id === selected) ?? null : null;

  function select(id: string) {
    setForkNote(null);
    setSelected((s) => (s === id ? null : id));
  }
  /** Fork inside a fork: start from one finished run of that fork (its change already applied). */
  function startForkInside(experimentId: string, nodeRunIdx: number) {
    const runId = experiments.find((e) => e.id === experimentId)?.tiles.find((t) => t.arm === "treatment" && t.run_id)?.run_id;
    if (!runId) {
      setForkNote("That fork has no finished run yet, so there is nothing to fork from. Wait for a run to finish, then try again.");
      return;
    }
    setForkNote(null);
    setBase({ experimentId, runId, nodeRun: nodeRunIdx });
    document.getElementById("run-dock")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function testSuggestion(nodeRun: number, patch: State) {
    setBase(null);
    setSuggest((prev) => ({ nodeRun, patch, nonce: (prev?.nonce ?? 0) + 1 }));
    setSelected(`a${nodeRun}`);
    document.getElementById("run-graph")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const benchmark = experiments.find((e) => e.benchmark)?.benchmark ?? null;
  const topSuspect = known && known.candidates.length ? known.candidates[(known.verification?.ranking ?? [0])[0]] : null;
  const showEditor = canFork && target !== null && (target.from === null || baseRun !== null);
  const editorRun = target?.from ? baseRun : run;
  const editorKey = `${target?.from ?? run.id}-${target?.nodeRun}-${suggest?.nodeRun === target?.nodeRun ? suggest?.nonce : 0}`;

  return (
    <div className="flex flex-col gap-10">
      <header className="grid items-end gap-6 lg:grid-cols-[1fr_auto]">
        <div className="flex flex-col gap-3">
          <Title className="max-w-3xl font-serif text-[1.75rem] leading-tight sm:text-[2.25rem]">
            {failed && got !== undefined && want !== undefined ? `The brief says ${got} open tickets, not ${want}.` : headline(run.outcome)}
          </Title>
          <Checks detail={run.oracle_detail} />
          {!run.outcome && mode === "app" && (
            <p className="max-w-[60ch] text-muted">
              Nothing has said whether this run is right. Add a check in code with the SDK (<code className="rounded bg-tile px-1.5 py-0.5 text-[0.8125rem]">submit_verdict</code>) and the run is marked right or wrong.
            </p>
          )}
          <p className="text-muted">
            {mode === "demo" && "Saved example. "}{run.workflow} · {formatTime(run.started_at)} · {run.steps.length} steps ·{" "}
            {formatTokens((run.tokens_in ?? 0) + (run.tokens_out ?? 0))} tokens
            {run.kind === "fork" && " · this run is part of a fork"}
          </p>
          {mode === "app" && <DeleteRun runId={run.id} />}
        </div>
        {got !== undefined && want !== undefined && (
          <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-line" style={{ gap: 1 }} aria-label="What the brief said and the real number">
            <div className="bg-sheet px-6 py-4">
              <p className="text-muted">The brief said</p>
              <p className="font-serif text-[3.25rem] leading-none text-bad">{got}</p>
              <p className="mt-1 text-muted">open tickets</p>
            </div>
            <div className="bg-sheet px-6 py-4">
              <p className="text-muted">The real number</p>
              <p className="font-serif text-[3.25rem] leading-none text-good">{want}</p>
              <p className="mt-1 text-muted">checked in code</p>
            </div>
          </div>
        )}
      </header>

      <section id="run-graph" aria-label="The run as a line" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div>
            <h2 className="font-serif text-2xl">How the run went</h2>
            <p className="text-muted">Left to right, in the order things ran. Select an agent to look inside it.</p>
          </div>
          <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.8125rem] text-muted" aria-label="Key">
            <li className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-bad" aria-hidden />Likely cause</li>
            <li className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-warn" aria-hidden />Affected by it</li>
            <li className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-full border border-dashed border-ink" aria-hidden />Changed by a fork</li>
          </ul>
        </div>
        <FlowGraph
          steps={run.steps} marks={marks} experiments={experiments} outcome={run.outcome} resultText={resultText}
          selected={selected} onSelect={(n) => select(n.id)} draft={draftRun === null ? null : { nodeRun: draftRun, fromExperiment: draftFrom }}
        />
        {forksError && (
          <p role="alert" className="rounded-lg border border-bad/30 bg-bad-tint px-3 py-2 text-bad">
            Could not load this run&apos;s forks ({forksError}). A fork you start will still run, but it will not show here until this loads. If you just updated the app, restart the API.
          </p>
        )}
        {forkNote && <p role="alert" className="rounded-lg border border-bad/30 bg-bad-tint px-3 py-2 text-bad">{forkNote}</p>}
        <details className="text-[0.8125rem] text-muted">
          <summary className="cursor-pointer hover:text-ink">How to read this line</summary>
          <div className="mt-2 flex max-w-[70ch] flex-col gap-2">
            {run.steps.some((s) => s.origin !== "recorded") && (
              <p>
                This run was made by a fork. <b className="font-medium text-ink">Replayed</b> steps are copied exactly from the recording and call no model.{" "}
                <b className="font-medium text-ink">Live</b> steps ran again against Claude, so they are sampled and can differ from run to run.
              </p>
            )}
            <p>A fork leaves the line at the dot, just before the agent it changed, and opens a new line under it. Each fork is run several times with the change and without it.</p>
            <p>In this workflow each agent waits for the one before it, so there are no side-by-side agents. AgentTrace records the order steps ran in, not their start times.</p>
          </div>
        </details>

        {/* The dock: what you selected, and (when you can change it) the editor beside it. */}
        <div id="run-dock" className="grid items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          {!node ? (
            <Guide
              className="lg:col-span-2" mode={mode} canFork={canFork}
              suspect={topSuspect ? { agent: agents.get(topSuspect.node_run_idx) ?? "agent", nodeRun: topSuspect.node_run_idx } : null}
              onPick={(nodeRun) => setSelected(`a${nodeRun}`)}
            />
          ) : (
            <>
              <div className={showEditor || (mode === "demo" && node.kind === "agent") ? "" : "lg:col-span-2"}>
                <NodePanel
                  node={node} run={run} report={known} experiments={experiments} mode={mode}
                  runHref={(id) => (mode === "demo" ? `/demo/runs/${id}` : `/runs/${id}`)}
                  experimentHref={(id) => (mode === "demo" ? null : `/experiments/${id}`)}
                  onForkBranch={startForkInside} canFork={canFork}
                />
              </div>
              {showEditor && editorRun && (
                <TestFixPanel
                  key={editorKey} run={editorRun}
                  request={{ nodeRunIdx: target!.nodeRun, patch: suggest?.nodeRun === target!.nodeRun ? suggest.patch : {} }}
                  baseLabel={target!.from ? graph.lanes.find((l) => l.experiment === target!.from)?.label.split(":")[0] : undefined}
                  onDirty={setDirty}
                  onLaunched={(id) => {
                    onForked?.(id);
                    setBase(null);
                    setSuggest(null);
                    setSelected(`${id}:end`);
                    document.getElementById("run-graph")?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                />
              )}
              {canFork && target?.from && !baseRun && !forkNote && <p className="card p-5 text-muted">Loading that fork&apos;s run…</p>}
              {mode === "demo" && node.kind === "agent" && (
                <section className="card flex flex-col gap-2 p-5 lg:sticky lg:top-4">
                  <h3 className="font-serif text-xl">Change it, then fork</h3>
                  <p className="text-muted">In your own workspace you edit what this agent produced here. A new line opens on the graph and everything after it runs again, with and without your change.</p>
                  <div><Link href="/sign-in" className="btn btn-primary">Sign in to fork</Link></div>
                </section>
              )}
            </>
          )}
        </div>
      </section>

      {mode === "app" && !canFork && (
        <section className="card p-5">
          <h2 className="font-serif text-xl">This run is view only</h2>
          <p className="mt-1 max-w-[60ch] text-muted">
            You can read every step on the line above. Forking and finding the cause run your agents again, so they need this
            workflow connected to a replay worker. That is not available yet, so runs you record or import yourself stay view only.
          </p>
        </section>
      )}
      {mode === "app" && canFork && <RcaPanel run={run} onTest={(c) => c.proposed_edit && testSuggestion(c.node_run_idx, c.proposed_edit.patch)} onReport={setSaved} />}
      {mode === "demo" && (
        <>
          {report && (
            <RcaView report={report} agentOf={(i) => agents.get(i) ?? "?"} canRun={false} busy={false}
              error={null} onFind={() => {}} onTest={() => {}} readOnly />
          )}
          {benchmark && <BenchmarkTable benchmark={benchmark} />}
          {extra}
          <section className="card p-5">
            <h2 className="font-serif text-xl">Fork a run of your own</h2>
            <p className="mt-1 text-muted">This example is read-only. Sign in to change what an agent decided and watch a new line open.</p>
            <Link href="/sign-in" className="btn btn-primary mt-3">Sign in</Link>
          </section>
        </>
      )}
    </div>
  );
}

/** Before anything is selected: what to do, in three short moves, and a way in at the likely cause. */
function Guide({
  mode, canFork, suspect, onPick, className = "",
}: { mode: "app" | "demo"; canFork: boolean; suspect: { agent: string; nodeRun: number } | null; onPick: (nodeRun: number) => void; className?: string }) {
  const steps = [
    ["Select an agent", "Click any agent on the line above."],
    ["Read it", "See what went in, what came out, and what it passed to the next agent."],
    [mode === "demo" ? "Sign in to fork" : canFork ? "Change it and fork" : "Look around", mode === "demo" ? "Change what it produced and a new line opens under the original." : canFork ? "Edit what it produced. A new line opens and everything after it runs again." : "This run is view only, so you can read every step but not fork it."],
  ] as const;
  return (
    <section className={`card p-5 ${className}`} aria-label="What to do next">
      <h3 className="font-serif text-xl">Select an agent on the line</h3>
      <ul className="mt-3 grid gap-3 sm:grid-cols-3">
        {steps.map(([title, text]) => (
          <li key={title} className="rounded-lg bg-tile p-3">
            <p className="font-medium">{title}</p>
            <p className="mt-0.5 text-muted">{text}</p>
          </li>
        ))}
      </ul>
      {suspect && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <p className="text-muted">The AI&apos;s best guess for the cause is the <b className="font-medium text-ink">{suspect.agent}</b>.</p>
          <button type="button" className="btn" onClick={() => onPick(suspect.nodeRun)}>Look at the {cap(suspect.agent)}</button>
        </div>
      )}
    </section>
  );
}
