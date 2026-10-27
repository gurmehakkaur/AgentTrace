import { ProjectBoard } from "@/components/project-board";
import { ExampleFrame } from "@/components/example-frame";
import type { Experiment, RunSummary, Tile } from "@/lib/types";

export const metadata = { title: "Example: all your runs by time" };

// Fixed times, not "now": a page built ahead of time must not read the clock. The chart fits whatever times it is given.
const at = (day: number, h: number, m = 0) => `2026-10-${day}T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00Z`;
const run = (id: string, workflow: string, outcome: "pass" | "fail", started: string): RunSummary => ({
  id, workflow, kind: "recorded", status: "ok", outcome, started_at: started, ended_at: started.replace(":00Z", ":40Z"),
});
const tiles = (c: number, t: number, n: number): Tile[] => [
  ...Array.from({ length: n }, (_, i): Tile => ({ arm: "control", i: i + 1, status: "done", run_id: null, outcome: i < c ? "pass" : "fail" })),
  ...Array.from({ length: n }, (_, i): Tile => ({ arm: "treatment", i: i + 1, status: "done", run_id: null, outcome: i < t ? "pass" : "fail" })),
];
const fork = (id: string, parent: string, started: string, agent: string, c: number, t: number, n: number, p: number): Experiment & { fork_agent: string } => ({
  id, status: "done", parent_run: parent, fork_node_run_idx: 1, n, edit_patch: {}, control: { pass: c, total: n }, treatment: { pass: t, total: n },
  tiles: tiles(c, t, n), stats: { fisher_p: p, wilson: { control: null, treatment: null }, label: `directional evidence, N=${n}` },
  tokens_used: 0, token_ceiling: 500000, error: null, created_at: started, fork_agent: agent,
});

const runs = [
  run("a1", "Renewal brief", "fail", at(23, 9, 2)), run("a2", "Renewal brief", "fail", at(23, 13, 40)), run("a3", "Renewal brief", "fail", at(23, 19, 15)),
  run("b1", "Support triage", "fail", at(23, 15, 10)), run("b2", "Support triage", "pass", at(23, 21, 30)), run("b3", "Support triage", "fail", at(24, 2, 5)), run("b4", "Support triage", "fail", at(24, 8, 45)),
  run("a4", "Renewal brief", "fail", at(24, 6, 20)),
];
const experiments = [
  fork("e1", "a1", at(23, 9, 40), "critic", 0, 0, 5, 1), fork("e2", "a1", at(23, 10, 15), "planner", 0, 8, 8, 0.00016),
  fork("e3", "a3", at(23, 19, 50), "writer", 0, 1, 5, 1),
  fork("e4", "b1", at(23, 15, 50), "router", 0, 5, 5, 0.0079), fork("e5", "b3", at(24, 2, 40), "responder", 0, 0, 5, 1), fork("e6", "b4", at(24, 9, 15), "router", 0, 3, 3, 0.1),
];

export default function Page() {
  return (
    <ExampleFrame path="/demo/overview" wide>
      <section className="flex flex-col gap-6">
        <h1 className="font-serif text-[1.5rem] sm:text-[1.75rem]">Runs</h1>
        <p className="max-w-[70ch] text-muted">
          This is the page you land on after signing in. Two workflows, eight runs, and the forks tried on them. Each run is a numbered row in
          its own colour; each fork is a diamond on the row under its run. A solid diamond helped, a hollow one did not. Click a filter to narrow it.
          In your workspace, clicking a row opens that run.
        </p>
        <ProjectBoard runs={runs} experiments={experiments} />
      </section>
    </ExampleFrame>
  );
}
