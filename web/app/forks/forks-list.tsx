"use client";

import Link from "next/link";
import { LoadState } from "@/components/load-state";
import { formatTime } from "@/lib/format";
import type { Experiment } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";
import { verdictFor } from "@/lib/verdict";

export function ForksList() {
  // Refreshes on its own, faster while a fork is still running.
  const state = useApiData<Experiment[]>("/v1/experiments", (list) => (list.some((e) => ["queued", "running"].includes(e.status)) ? 2000 : 6000));
  return (
    <LoadState state={state}>
      {(all) => {
        const forks = [...all].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
        if (forks.length === 0) {
          return (
            <div className="card flex flex-col gap-3 p-6">
              <h2 className="font-serif text-xl">No forks yet</h2>
              <p className="max-w-[60ch] text-muted">Open a run, select an agent on its line and click Fork here. Change what that agent produced, and a new line opens.</p>
              <div><Link href="/runs" className="btn btn-primary">Open your runs</Link></div>
            </div>
          );
        }
        return (
          <ul className="card divide-y divide-line">
            {forks.map((e) => {
              const running = ["queued", "running"].includes(e.status);
              const verdict = running ? null : verdictFor(e.control, e.treatment, e.stats.fisher_p);
              return (
                <li key={e.id}>
                  <Link href={`/runs/${e.parent_run}?fork=${e.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-4 hover:bg-tile/60">
                    <span className={`rounded-full border px-3 py-0.5 font-medium ${running ? "border-line bg-tile" : verdict?.tone === "good" ? "border-good/40 bg-good-tint text-good" : verdict?.tone === "bad" ? "border-bad/40 bg-bad-tint text-bad" : "border-line bg-tile"}`}>
                      {running ? "Running…" : `${e.treatment.pass} of ${e.treatment.total} right`}
                    </span>
                    <span>{running ? "Still running" : verdict?.text ?? "No result yet"}</span>
                    <span className="text-muted">
                      without the change {e.control.pass} of {e.control.total} · changed {Object.keys(e.edit_patch).join(", ") || "a value"}
                    </span>
                    {e.created_at && <span className="ml-auto text-[0.8125rem] text-muted">{formatTime(e.created_at)}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        );
      }}
    </LoadState>
  );
}
