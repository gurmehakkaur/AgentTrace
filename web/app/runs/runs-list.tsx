"use client";

import Link from "next/link";
import { LoadState } from "@/components/load-state";
import { ProjectBoard } from "@/components/project-board";
import { SampleRunButton } from "@/components/sample-run-button";
import type { Experiment, RunSummary } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

export function RunsList() {
  // Recorded runs only: every fork also records a run per attempt, and they would bury the real ones.
  // Both lists refresh on their own, so a run recorded or a fork started elsewhere shows up here.
  const state = useApiData<RunSummary[]>("/v1/runs?kind=recorded&limit=200", () => 5000);
  const forks = useApiData<Experiment[]>("/v1/experiments", (list) => (list.some((e) => ["queued", "running"].includes(e.status)) ? 2000 : 5000));

  return (
    <LoadState state={state}>
      {(runs) =>
        runs.length === 0 ? (
          <div className="card flex flex-col gap-3 p-6">
            <h2 className="font-serif text-xl">No runs yet</h2>
            <p className="max-w-[60ch] text-muted">
              The quickest way to see AgentTrace work is to add the saved example to this workspace. You can then open its line
              and fork it. Or connect your own agents.
            </p>
            <div className="flex flex-wrap items-start gap-3">
              <SampleRunButton />
              <Link href="/connect" className="btn">Connect your agents</Link>
            </div>
          </div>
        ) : (
          <ProjectBoard runs={runs} experiments={forks.status === "ok" ? forks.data : []} />
        )
      }
    </LoadState>
  );
}
