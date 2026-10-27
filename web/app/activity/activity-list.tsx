"use client";

import { useAuth } from "@clerk/nextjs";
import { formatTime } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";

type Row = { actor: string; action: string; target: string; at: string };

const WORDS: Record<string, string> = {
  "experiment.launch": "Started a fork",
  "rca.run": "Looked for the cause of a run",
  "rca.verify": "Checked the top suspects by experiment",
  "run.delete": "Deleted a run",
  "run.import": "Imported a run",
  "key.create": "Made a key",
  "key.revoke": "Stopped a key",
};

export function ActivityList() {
  const { userId } = useAuth();
  const state = useApiData<Row[]>("/v1/audit?limit=100", () => 10000);
  if (state.status === "loading") return <p className="text-muted">Loading…</p>;
  if (state.status === "error") {
    return (
      <p role="alert" className="card p-5 text-muted">
        {state.code === 403 ? "Only organization admins can read the activity log." : `Could not load the activity log (${state.message}).`}
      </p>
    );
  }
  if (state.data.length === 0) return <p className="card p-5 text-muted">Nothing has happened in this workspace yet.</p>;
  return (
    <ul className="card divide-y divide-line">
      {state.data.map((r, i) => (
        <li key={`${r.at}-${i}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3">
          <span className="font-medium">{WORDS[r.action] ?? r.action}</span>
          <span className="text-muted">by {r.actor === userId ? "you" : r.actor.slice(0, 14)}</span>
          <code className="font-mono text-[0.8125rem] text-muted">{r.target.slice(0, 12)}</code>
          <span className="ml-auto text-[0.8125rem] text-muted">{formatTime(r.at)}</span>
        </li>
      ))}
    </ul>
  );
}
