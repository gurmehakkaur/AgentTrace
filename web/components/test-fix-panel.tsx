"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, useApi } from "@/lib/api";
import { diffState } from "@/lib/diff";
import { forkPrefill, nodeRuns } from "@/lib/runs";
import { brief } from "@/lib/story";
import type { Run, State } from "@/lib/types";

const N_CHOICES = [3, 5, 8];

const asText = (v: unknown) => JSON.stringify(v, null, 2);

/** The fork editor, beside the details of the agent you selected. You see what went in and what came out
 * on the left; here you change what came out, choose how many runs, and fork. Everything before the agent
 * is replayed exactly; everything after it runs again, with your change and without it. */
export function TestFixPanel({
  run, request, onLaunched, baseLabel, onDirty,
}: {
  run: Run;
  request?: { nodeRunIdx: number; patch: State } | null;
  onLaunched: (experimentId: string) => void;
  baseLabel?: string;
  onDirty?: (dirty: boolean) => void; // true once there is a change, so the graph can draw the new line
}) {
  const api = useApi();
  const forkable = useMemo(() => nodeRuns(run.steps).filter((r) => r.stateAfter && r.writes.length > 0), [run.steps]);
  // The agent to change is the one that was selected on the line. There is no second place to choose it.
  const selected = forkable.find((r) => r.idx === request?.nodeRunIdx);
  const prefill = useMemo(() => (selected ? forkPrefill(selected) : {}), [selected]);
  // One editor per value the agent wrote. A suggested fix arrives already applied.
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(selected ? forkPrefill(selected) : {}).map(([k, v]) => [k, asText(request?.patch?.[k] ?? v)])),
  );
  const [n, setN] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const parsed = Object.keys(prefill).map((key) => {
    try {
      return { key, value: JSON.parse(texts[key] ?? asText(prefill[key])) as unknown, error: null };
    } catch {
      return { key, value: undefined, error: "This is not valid JSON yet." };
    }
  });
  const edit: State = Object.fromEntries(
    parsed.filter((p) => !p.error && JSON.stringify(p.value) !== JSON.stringify(prefill[p.key])).map((p) => [p.key, p.value]),
  );
  const lines = Object.keys(edit).flatMap((key) =>
    diffState({ [key]: prefill[key] }, { [key]: edit[key] }).map((c) => ({
      id: `${key}:${c.path}`,
      path: c.path.split(".").slice(-2).join("."),
      before: c.kind === "added" ? "nothing" : brief(c.before, 50),
      after: c.kind === "removed" ? "nothing" : brief(c.after, 50),
    })),
  );
  const dirty = lines.length > 0;
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);

  if (!selected) {
    return (
      <section id="test-fix" tabIndex={-1} aria-label="Fork" className="card flex flex-col gap-1 p-5">
        <h3 className="font-serif text-xl">Nothing to change here</h3>
        <p className="text-muted">This agent did not write any value the next agent uses. Select a different agent on the line.</p>
      </section>
    );
  }

  const invalid = parsed.find((p) => p.error);
  const problem = invalid ? `Fix the JSON in "${invalid.key}" first.` : !dirty ? "Change a value above to see what it does." : null;
  const forkAt = selected.idx;
  async function launch() {
    setSubmitting(true);
    setApiError(null);
    try {
      const { id } = await api<{ id: string }>("/v1/experiments", {
        method: "POST",
        body: JSON.stringify({ run_id: run.id, fork_node_run_idx: forkAt, edit, n }),
      });
      setSubmitting(false);
      onLaunched(id);
    } catch (err) {
      setApiError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
      setSubmitting(false);
    }
  }

  return (
    <section id="test-fix" tabIndex={-1} aria-label="Change it and fork" className="card flex flex-col gap-4 p-5 lg:sticky lg:top-4">
      <div>
        <h3 className="font-serif text-xl">Change it, then fork</h3>
        <p className="mt-1 text-muted">
          Edit what the <span className="capitalize">{selected.agent}</span> produced. A new line opens on the graph and everything after it
          runs again, with your change and without it.
        </p>
        {baseLabel && (
          <p className="mt-2 rounded-lg border border-line bg-tile px-3 py-2">
            Starts from one run of <b className="font-medium">{baseLabel}</b>, with that fork&apos;s change already applied.
          </p>
        )}
      </div>

      {Object.keys(prefill).map((key) => {
        const p = parsed.find((x) => x.key === key);
        return (
          <div key={key} className="flex flex-col gap-1">
            <label htmlFor={`edit-${key}`} className="font-mono text-[0.8125rem] text-muted">{key}</label>
            <textarea
              id={`edit-${key}`}
              value={texts[key] ?? ""}
              onChange={(e) => setTexts((t) => ({ ...t, [key]: e.target.value }))}
              spellCheck={false}
              rows={Math.min(10, Math.max(4, (texts[key] ?? "").split("\n").length + 1))}
              aria-invalid={!!p?.error}
              className="rounded-lg border border-ink/30 bg-frame p-3 font-mono text-xs leading-relaxed"
            />
            {p?.error && <p role="alert" className="text-bad">{p.error}</p>}
          </div>
        );
      })}

      {dirty && (
        <div className="rounded-lg border border-line bg-frame p-3" aria-live="polite">
          <p className="font-medium">Your change</p>
          <ul className="mt-1 space-y-1 font-mono text-xs">
            {lines.map((l) => (
              <li key={l.id} className="[overflow-wrap:anywhere]">
                <span>{l.path}: </span>
                <span className="text-bad line-through decoration-bad/60">{l.before}</span>
                <span aria-hidden className="text-muted"> → </span>
                <span className="sr-only"> became </span>
                <span className="text-good">{l.after}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <p className="font-medium" id="runs-label">How many runs?</p>
        <div role="group" aria-labelledby="runs-label" className="flex flex-wrap items-center gap-2">
          {N_CHOICES.map((choice) => (
            <button
              key={choice}
              type="button"
              onClick={() => setN(choice)}
              aria-pressed={n === choice}
              className={`rounded-lg border px-4 py-1.5 font-medium tabular-nums ${n === choice ? "border-ink bg-ink text-frame" : "border-ink/30 hover:bg-ink/5"}`}
            >
              {choice}
            </button>
          ))}
          <span className="text-muted">{n} without + {n} with = {2 * n} runs</span>
        </div>
      </div>

      <div className="flex flex-col items-start gap-2">
        <button type="button" onClick={launch} disabled={problem !== null || submitting} className="btn btn-primary w-full py-2.5">
          {submitting ? "Opening the new line…" : `Fork and run (${2 * n} runs)`}
        </button>
        <p role="alert" className="min-h-5 text-muted">{apiError ? <span className="text-bad">{apiError}</span> : problem}</p>
        <p className="text-[0.8125rem] text-muted">
          {run.fork_mode === "worker" && "This run is forked by the worker you run next to your code, so start it first (Connect your agents). "}
          You can change what an agent wrote. You cannot yet change its instructions and run it again; that needs your workflow code.
          Runs after the agent are live, so results can vary. That is why each side is repeated.
        </p>
      </div>
    </section>
  );
}
