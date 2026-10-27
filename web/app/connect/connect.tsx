"use client";

import Link from "next/link";
import { useState } from "react";
import { SampleRunButton } from "@/components/sample-run-button";
import { Alerts } from "./alerts";
import { ApiError, useApi } from "@/lib/api";
import { describeScopes, KEY_KINDS, usage } from "@/lib/keys";
import { useApiData } from "@/lib/use-api-data";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://your-agenttrace-api";

type KeyRow = { id: string; prefix: string; scopes?: string[]; created_at?: string; last_seen_at?: string | null; revoked_at?: string | null };

export function snippet(key: string): string {
  return `import asyncio
from anthropic import AsyncAnthropic
from agenttrace_sdk import HttpSink, TracedLLM, node, trace_run

client = AsyncAnthropic()
sink = HttpSink("${API_URL}", "${key}")

# One @node per agent. Say which parts of the shared state it reads and writes.
@node("planner", reads=["request"], writes=["plan"])
async def planner(state, llm, tools):
    reply = await llm.create(
        model="claude-haiku-5-5", max_tokens=1000,
        messages=[{"role": "user", "content": state["request"]}],
    )
    return {"plan": next(b.text for b in reply.content if b.type == "text")}

async def main():
    async with trace_run("my_workflow", sink) as run:
        state = {"request": "Write a renewal brief for account 103"}
        state |= await planner(state, TracedLLM(client, "planner"), None)
        # Call your other agents the same way, one @node each.
        run.outcome = "pass"  # or "fail": your own check of the answer

asyncio.run(main())`;
}

const PIP = 'pip install "git+https://github.com/AjayMaan13/AgentTrace.git#subdirectory=sdk"';

const EXAMPLE_LOG = JSON.stringify(
  {
    workflow: "support_bot",
    outcome: "fail",
    steps: [
      { agent: "router", input: "I want a refund for order 1182", output: "route: billing" },
      { agent: "billing", kind: "tool", tool_name: "lookup_order", tool_args: { id: 1182 }, tool_result: { found: false } },
      { agent: "billing", output: "I could not find that order.", state_after: { answer: "order not found" } },
      { agent: "reviewer", output: "approve" },
    ],
  },
  null,
  2,
);

export function Connect() {
  const api = useApi();
  const [tick, setTick] = useState(0);
  const keys = useApiData<KeyRow[]>(`/v1/keys?k=${tick}`);
  const [fresh, setFresh] = useState<string | null>(null);
  const [kindId, setKindId] = useState(KEY_KINDS[0].id);
  const [freshKind, setFreshKind] = useState(KEY_KINDS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  async function mint() {
    setBusy(true);
    setError(null);
    try {
      const kind = KEY_KINDS.find((k) => k.id === kindId) ?? KEY_KINDS[0];
      const { key } = await api<{ key: string }>("/v1/keys", { method: "POST", body: JSON.stringify({ scopes: kind.scopes }) });
      setFresh(key);
      setFreshKind(kind);
      setTick((t) => t + 1);
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: string) {
    if (!window.confirm("Stop this key from working? Anything still using it will be refused.")) return;
    try {
      await api(`/v1/keys/${id}`, { method: "DELETE" });
      setTick((t) => t + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }
  async function copy(what: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      setError("Your browser would not let us copy. Select the text and copy it yourself.");
    }
  }

  const code = snippet(fresh ?? "YOUR_KEY");
  return (
    <div className="flex flex-col gap-12">
      <section className="card flex flex-col gap-3 p-5" aria-label="Start with an example">
        <div>
          <h2 className="font-serif text-2xl">Want to try forking first?</h2>
          <p className="mt-1 max-w-[60ch] text-muted">
            Add a real run that went wrong to this workspace. It is the saved example from the demo. You can open its line, find the
            cause and fork it straight away. It costs nothing to add, and no code is needed.
          </p>
        </div>
        <SampleRunButton />
      </section>

      <section className="flex flex-col gap-4" aria-label="Make a key">
        <div>
          <h2 className="font-serif text-2xl">1. Make a key</h2>
          <p className="mt-1 max-w-[60ch] text-muted">
            A key lets your code send runs to this workspace. We show it once, so copy it now. We keep only a fingerprint.
            A key can do only what you choose here.
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="key-kind" className="font-medium">What is this key for?</label>
          <select id="key-kind" value={kindId} onChange={(e) => setKindId(e.target.value)} className="max-w-md rounded-lg border border-line bg-tile px-3 py-2">
            {KEY_KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
          <p className="max-w-[60ch] text-[0.8125rem] text-muted">{(KEY_KINDS.find((k) => k.id === kindId) ?? KEY_KINDS[0]).hint}</p>
        </div>
        <div>
          <button type="button" className="btn btn-primary" onClick={mint} disabled={busy}>
            {busy ? "Making a key…" : "Make a key"}
          </button>
        </div>
        {error && <p role="alert" className="text-bad">{error}</p>}
        {fresh && (
          <div className="card flex flex-col gap-2 p-4">
            <p className="font-medium text-good">Your key. It will not be shown again.</p>
            <code className="block rounded-lg bg-tile p-3 font-mono text-[0.8125rem] [overflow-wrap:anywhere]">{fresh}</code>
            <div><button type="button" className="btn" onClick={() => copy("key", fresh)}>{copied === "key" ? "Copied" : "Copy the key"}</button></div>
            {usage(freshKind, fresh, API_URL) && <pre tabIndex={0} className="overflow-x-auto rounded-lg bg-tile p-3 font-mono text-[0.8125rem] leading-relaxed">{usage(freshKind, fresh, API_URL)}</pre>}
          </div>
        )}
        {keys.status === "ok" && keys.data.length > 0 && (
          <ul className="card divide-y divide-line">
            {keys.data.map((k) => (
              <li key={k.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <code className="font-mono text-[0.8125rem]">{k.prefix}…</code>
                <span className="text-muted">{k.revoked_at ? "stopped" : "working"} · can {describeScopes(k.scopes)}</span>
                {k.created_at && <span className="text-[0.8125rem] text-muted">made {new Date(k.created_at).toLocaleDateString()}</span>}
                {k.last_seen_at && <span className="text-[0.8125rem] text-muted">last asked {new Date(k.last_seen_at).toLocaleTimeString()}</span>}
                {!k.revoked_at && <button type="button" className="btn ml-auto" onClick={() => revoke(k.id)}>Stop this key</button>}
              </li>
            ))}
          </ul>
        )}
        {keys.status === "error" && keys.code === 403 && (
          <p className="text-muted">Only organization admins can make keys. Ask an admin of this organization.</p>
        )}
      </section>

      <section className="flex flex-col gap-4" aria-label="Add the recorder">
        <div>
          <h2 className="font-serif text-2xl">2. Add the recorder to your code</h2>
          <p className="mt-1 max-w-[60ch] text-muted">
            Install the Python recorder, wrap each agent, and run your workflow as you normally do. Each run becomes a line. Secrets
            such as emails and API keys are removed before anything leaves your machine.
          </p>
        </div>
        <pre tabIndex={0} className="card overflow-x-auto p-4 font-mono text-[0.8125rem] leading-relaxed">{PIP}</pre>
        <pre tabIndex={0} className="card max-h-[28rem] overflow-auto p-4 font-mono text-[0.8125rem] leading-relaxed">{code}</pre>
        <div><button type="button" className="btn" onClick={() => copy("code", code)}>{copied === "code" ? "Copied" : "Copy the code"}</button></div>
        <p className="max-w-[60ch] text-[0.8125rem] text-muted">
          Recording and the line work for any Python workflow that calls Claude. Forking and finding the cause re-run your agents,
          so they need your workflow connected to a replay worker, which is not available yet. Until then your runs are view only.
        </p>
      </section>

      <Import />
      <Alerts />
    </div>
  );
}

function Import() {
  const api = useApi();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ id: string; steps: number }[]>([]);

  async function run() {
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError("That is not valid JSON yet. Paste the contents of your log file, or load the example to see the shape.");
      return;
    }
    const logs = Array.isArray(parsed) ? parsed : [parsed];
    setBusy(true);
    const made: { id: string; steps: number }[] = [];
    try {
      for (const log of logs) made.push(await api<{ id: string; steps: number }>("/v1/runs/import", { method: "POST", body: JSON.stringify(log) }));
      setDone(made);
    } catch (err) {
      setDone(made);
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-4" aria-label="Bring your past runs">
      <div>
        <h2 className="font-serif text-2xl">3. Bring runs you already have</h2>
        <p className="mt-1 max-w-[60ch] text-muted">
          Paste a log in the shape below, or upload a file. Each log becomes a run you can open as a line. Imported runs are view
          only: you can read every step, but not fork them.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn" onClick={() => setText(EXAMPLE_LOG)}>Load an example</button>
        <label className="btn cursor-pointer">
          Upload a .json file
          <input
            type="file" accept="application/json,.json" className="sr-only"
            onChange={async (e) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); e.target.value = ""; }}
          />
        </label>
      </div>
      <label htmlFor="log" className="sr-only">Your log as JSON</label>
      <textarea
        id="log" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} rows={12}
        placeholder='{ "workflow": "my_workflow", "steps": [ { "agent": "planner", "input": "…", "output": "…" } ] }'
        className="card p-3 font-mono text-[0.8125rem] leading-relaxed"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-primary" onClick={run} disabled={busy || !text.trim()}>
          {busy ? "Importing…" : "Import"}
        </button>
        {error && <p role="alert" className="text-bad">{error}</p>}
      </div>
      {done.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {done.map((d) => (
            <li key={d.id}>
              Imported {d.steps} steps.{" "}
              <Link href={`/runs/${d.id}`} className="underline underline-offset-4">Open the run</Link>
            </li>
          ))}
        </ul>
      )}
      <details className="card p-4">
        <summary className="cursor-pointer">The shape of a log</summary>
        <div className="mt-3 flex flex-col gap-2 text-muted">
          <p>One object per run, or a list of them. Only <code className="font-mono">workflow</code> and each step&apos;s <code className="font-mono">agent</code> are required.</p>
          <ul className="list-disc pl-5">
            <li><code className="font-mono">outcome</code>: &quot;pass&quot; or &quot;fail&quot;, if you know it.</li>
            <li><code className="font-mono">kind</code>: &quot;llm&quot; (the default) or &quot;tool&quot;, with <code className="font-mono">tool_name</code>, <code className="font-mono">tool_args</code> and <code className="font-mono">tool_result</code>.</li>
            <li><code className="font-mono">input</code> and <code className="font-mono">output</code>: what the agent was given and answered.</li>
            <li>Steps by the same agent in a row count as one turn. Use <code className="font-mono">node</code> (a number) to group them yourself.</li>
          </ul>
          <p>From a script, send the same JSON to <code className="font-mono">POST {API_URL}/v1/import</code> with <code className="font-mono">Authorization: Bearer YOUR_KEY</code>.</p>
        </div>
      </details>
    </section>
  );
}
