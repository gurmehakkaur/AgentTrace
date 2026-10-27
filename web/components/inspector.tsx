import { OriginBadge, ORIGINS } from "@/components/badges";
import { JsonBlock } from "@/components/json-block";
import { diffState } from "@/lib/diff";
import { formatTokens } from "@/lib/format";
import { nodeRuns, stateBefore } from "@/lib/runs";
import { brief } from "@/lib/story";
import type { Step } from "@/lib/types";

/** The text of a model reply or message: the text blocks of `{content: [...]}`, or the string itself. */
export function textOf(value: unknown): string | null {
  if (typeof value === "string") return value;
  const content = (value as { content?: unknown } | null)?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const text = content.map((b) => (typeof b === "string" ? b : (b as { type?: string; text?: string })?.type === "text" ? (b as { text: string }).text : "")).join("\n").trim();
    return text || null;
  }
  return null;
}

/** What this model call was asked: the last message it was given. */
export function askedOf(step: Step): string | null {
  const messages = (step.input as { messages?: unknown[] } | null)?.messages;
  if (!Array.isArray(messages) || messages.length === 0) return null;
  return textOf(messages[messages.length - 1]);
}

/** One step, in the order a person asks about it: what it was asked, what it answered, what it
 * handed to the next agent. Prompts, tokens and raw data are folded under "Technical details". */
export function Inspector({ step, steps }: { step: Step | null; steps: Step[] }) {
  if (!step) return <p className="text-muted">Select a step to see what happened in it.</p>;

  const runs = nodeRuns(steps);
  const turn = runs.find((r) => r.idx === step.node_run_idx);
  const changes = turn ? diffState(stateBefore(runs, turn.idx), turn.stateAfter) : [];
  const input = step.input as { system?: unknown; messages?: unknown } | null;
  const asked = step.kind === "llm" ? askedOf(step) : null;
  const answered = step.kind === "llm" ? textOf(step.output) : null;
  const many = (turn?.steps.length ?? 1) > 1;

  return (
    <div className="flex flex-col gap-5">
      <Part title={step.kind === "tool" ? `It asked the ${step.tool_name ?? "tool"} tool` : "What it was asked"}>
        {step.kind === "tool" ? (
          <Quote text={JSON.stringify(step.tool_args ?? {}, null, 2)} code />
        ) : asked ? (
          <Quote text={asked} />
        ) : (
          <p className="text-muted">No question was recorded for this step.</p>
        )}
      </Part>

      <Part title={step.kind === "tool" ? "What came back" : "What it answered"}>
        {step.kind === "tool" ? (
          <Quote text={typeof step.tool_result === "string" ? step.tool_result : JSON.stringify(step.tool_result, null, 2)} code />
        ) : answered ? (
          <Quote text={answered} />
        ) : (
          <JsonBlock label="Raw answer" value={step.output} />
        )}
      </Part>

      <Part title="What it passed to the next agent" hint={many ? "Across all of this agent's steps." : undefined}>
        {changes.length === 0 ? (
          <p className="text-muted">It did not change anything the next agent can see.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {changes.map((c) => (
              <li key={c.path} className="rounded-lg bg-tile px-3 py-2">
                <code className="font-mono text-[0.8125rem] text-ink [overflow-wrap:anywhere]">{c.path}</code>
                <p className="mt-0.5 text-muted [overflow-wrap:anywhere]">
                  {c.kind === "added" ? "now " : c.kind === "removed" ? "removed " : `${brief(c.before, 60)} → `}
                  {c.kind !== "removed" && <span className="text-ink">{brief(c.after, 90)}</span>}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Part>

      <details className="rounded-lg border border-line p-3">
        <summary className="cursor-pointer text-muted">Technical details</summary>
        <div className="mt-3 flex flex-col gap-4">
          <p className="flex flex-wrap items-center gap-2">
            <OriginBadge origin={step.origin} />
            <span className="text-muted">{ORIGINS[step.origin].meaning}.</span>
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
            <Fact label="Model" value={step.model ?? "none (tool)"} />
            <Fact label="Tokens in" value={formatTokens(step.tokens_in)} />
            <Fact label="Tokens out" value={formatTokens(step.tokens_out)} />
            <Fact label="Time" value={`${step.latency_ms} ms`} />
          </dl>
          {typeof input?.system === "string" && <JsonBlock label="Instructions it was given" value={input.system} />}
          {step.kind === "llm" && <JsonBlock label="Everything it was sent" value={input?.messages} />}
          <JsonBlock label={step.kind === "tool" ? "Raw result" : "Raw answer"} value={step.kind === "tool" ? step.tool_result : step.output} />
          <p className="text-muted">
            Read from the shared state: {step.reads.join(", ") || "nothing"} · Wrote: {step.writes.join(", ") || "nothing"}
            {step.redactions.length > 0 && ` · ${step.redactions.length} secret value(s) were removed before storage`}
          </p>
        </div>
      </details>
    </div>
  );
}

function Part({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="text-[0.9375rem] font-medium">{title}</h4>
      {hint && <p className="text-[0.8125rem] text-muted">{hint}</p>}
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Quote({ text, code = false }: { text: string; code?: boolean }) {
  return (
    <pre
      tabIndex={0}
      className={`max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-tile p-3 leading-relaxed [overflow-wrap:anywhere] ${code ? "font-mono text-[0.8125rem]" : "font-sans text-[0.9375rem]"}`}
    >
      {text}
    </pre>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.8125rem] text-muted">{label}</dt>
      <dd className="break-words font-medium">{value}</dd>
    </div>
  );
}

