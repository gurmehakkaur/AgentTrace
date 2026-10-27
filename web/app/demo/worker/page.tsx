import { ExampleFrame } from "@/components/example-frame";
import { ExperimentView } from "@/components/experiment-view";
import type { Experiment, Tile } from "@/lib/types";

export const metadata = { title: "Example: forking your own agents" };

const tiles = (c: number, t: number, n: number, status = "done"): Tile[] => [
  ...Array.from({ length: n }, (_, i): Tile => ({ arm: "control", i: i + 1, status: status as Tile["status"], run_id: status === "done" ? `c${i}` : null, outcome: status !== "done" ? null : i < c ? "pass" : "fail" })),
  ...Array.from({ length: n }, (_, i): Tile => ({ arm: "treatment", i: i + 1, status: status as Tile["status"], run_id: status === "done" ? `t${i}` : null, outcome: status !== "done" ? null : i < t ? "pass" : "fail" })),
];
const base = { parent_run: "9f2c41a7d0", fork_node_run_idx: 1, edit_patch: { category: "billing" }, tokens_used: 0, token_ceiling: 500000, error: null, created_at: "2026-10-24T09:30:00Z", mode: "worker" as const };

const waiting = {
  ...base, id: "w-waiting", status: "queued", n: 3, control: { pass: 0, total: 0 }, treatment: { pass: 0, total: 0 }, tiles: tiles(0, 0, 3, "queued"),
  stats: { fisher_p: null, wilson: { control: null, treatment: null }, label: "directional evidence, N=3" }, workers_online: 0,
} as unknown as Experiment;
const finished = {
  ...base, id: "w-done", status: "done", n: 5, control: { pass: 0, total: 5 }, treatment: { pass: 5, total: 5 }, tiles: tiles(0, 5, 5),
  stats: { fisher_p: 0.0079, wilson: { control: [0, 0.43], treatment: [0.57, 1] }, label: "directional evidence, N=5" }, workers_online: 1, tokens_used: 1350,
} as unknown as Experiment;

const CODE = `from agenttrace_sdk import Worker

async def resume(state, rec):
    # The recording up to the fork point, with the change applied for the runs that have it.
    # Run YOUR agents from here and record each turn.
    reply = await my_responder(state)
    state = {**state, "reply": reply}
    await rec.turn("responder", input=..., output=reply, state_after=state, writes=["reply"])
    return state

def check(state):                       # YOUR definition of a right answer
    return "refund" in state["reply"].lower(), "the reply handles the refund"

worker = Worker("https://<your-api>", "at_live_...")   # a key made for a worker
worker.register("support-triage", resume, oracle=check, safe_to_rerun=True)
asyncio.run(worker.run_forever())`;

export default function Page() {
  return (
    <ExampleFrame path="/demo/worker">
      <section className="flex flex-col gap-3">
        <h1 className="font-serif text-[1.75rem] sm:text-[2.25rem]">Forking agents that run on your own system</h1>
        <p className="max-w-[70ch] text-muted">
          AgentTrace cannot re-run an agent it did not build. So a small worker runs next to your code and connects out to AgentTrace (nothing connects in).
          When you fork one of your runs, the worker takes the jobs, runs your agents again from the fork point, and reports back. Steps before the fork
          replay exactly from the recording; the rest run live, so each side is repeated and the result is directional, never proof.
        </p>
      </section>

      <section className="flex flex-col gap-3" aria-label="The worker">
        <h2 className="font-serif text-xl">The worker, in a dozen lines</h2>
        <pre tabIndex={0} className="card overflow-x-auto p-4 font-mono text-[0.8125rem] leading-relaxed">{CODE}</pre>
        <p className="max-w-[70ch] text-[0.8125rem] text-muted">
          <code>safe_to_rerun=True</code> has no default. A fork runs your agents again, live, several times, and AgentTrace cannot see inside your
          code, so you are the one saying that is safe: no real emails or payments, or those tools are mocked.
        </p>
      </section>

      <section className="flex flex-col gap-3" aria-label="Before the worker takes a job">
        <h2 className="font-serif text-xl">1. You fork a run. The experiment waits for the worker.</h2>
        <ExperimentView experiment={waiting} title="Test result" level={2} runHref={() => "#"} />
      </section>

      <section className="flex flex-col gap-3" aria-label="After">
        <h2 className="font-serif text-xl">2. The worker runs the jobs. This is what comes back.</h2>
        <p className="max-w-[70ch] text-muted">
          Support triage sent a refund request to shipping, so the customer got a delivery message. Changing the router&apos;s category to billing
          and running the rest again: 0 of 5 right without the change, 5 of 5 with it.
        </p>
        <ExperimentView experiment={finished} title="Test result" level={2} runHref={() => "#"} />
      </section>
    </ExampleFrame>
  );
}
