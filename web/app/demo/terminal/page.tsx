import { ExampleFrame } from "@/components/example-frame";

export const metadata = { title: "Example: from your terminal and CI" };

// These two blocks are copied from a real run of api/scripts/addon_smoke.py (the real API and database, no model).
const GATE_OK = `$ agenttrace gate 38ed0244… --min-pass 0.75
The fix held: with the change 3 of 3 right, without it 0 of 3 (p = 0.1000, directional). Needed at least 75% right with the change.
$ echo $?
0`;
const GATE_BAD = `$ agenttrace gate 94b9f8de… --min-pass 0.75
The fix regressed: with the change 0 of 3 right, without it 0 of 3 (p = 1.0000, directional). Needed at least 75% right with the change.
$ echo $?
1`;
const LOOK = `$ export AGENTTRACE_URL=https://<your-api> AGENTTRACE_KEY=at_live_...
$ agenttrace failed
f750b94f…  support-triage (sample data)  fail  2026-10-24T09:12:00Z
$ agenttrace show f750b94f…
f750b94f…  support-triage (sample data)  outcome: fail
check refund_handled: the customer asked for a refund and the reply never mentions one
    1  turn 1  router     llm   recorded
    2  turn 2  responder  llm   recorded
    3  turn 2  responder  tool  recorded
    4  turn 3  reviewer   llm   recorded
$ agenttrace suspects f750b94f…           # a key that may spend; costs tokens
turn 1  80%  the router sent a refund request to shipping
$ agenttrace fork f750b94f… 1 --edit '{"category": "billing"}' -n 5
Started experiment 38ed0244…`;
const MCP = `{
  "mcpServers": {
    "agenttrace": {
      "command": "agenttrace-mcp",
      "env": { "AGENTTRACE_URL": "https://<your-api>", "AGENTTRACE_KEY": "at_live_..." }
    }
  }
}`;

function Block({ title, text }: { title: string; text: string }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-serif text-xl">{title}</h2>
      <pre tabIndex={0} className="card overflow-x-auto p-4 font-mono text-[0.8125rem] leading-relaxed">{text}</pre>
    </section>
  );
}

export default function Page() {
  return (
    <ExampleFrame path="/demo/terminal">
      <section className="flex flex-col gap-3">
        <h1 className="font-serif text-[1.75rem] sm:text-[2.25rem]">From your terminal, your assistant and your pipeline</h1>
        <p className="max-w-[70ch] text-muted">
          The same things you do in the app, as a command line and as tools an assistant can call. A key decides what the caller may do: one that can read
          only looks; one that can spend may also ask which step broke a run and start experiments, which cost tokens and fall under the same limits as a person.
        </p>
      </section>
      <Block title="Look at what failed, ask why, test a fix" text={LOOK} />
      <Block title="In your pipeline: does a fix we proved still work?" text={GATE_OK} />
      <Block title="…and when the new code broke it" text={GATE_BAD} />
      <p className="max-w-[70ch] text-[0.8125rem] text-muted">
        The gate re-runs the experiment against the code about to ship and exits 0 if the runs with the change still came out right often enough, 1 if not,
        and 2 if it could not tell. Treat 1 and 2 as a failed check. Live steps are sampled, so one flaky run moves the rate: use a larger N, or a lower bar, if your workflow is noisy.
        The two blocks above are from a real run against the real API and database.
      </p>
      <Block title="Let an assistant look: any MCP client" text={MCP} />
      <p className="max-w-[70ch] text-[0.8125rem] text-muted">
        Tools: list failed runs, read a run, rank suspects, start an experiment, read its result. What an assistant reads from a run is marked as data, not
        instructions, and long text is cut short.
      </p>
    </ExampleFrame>
  );
}
