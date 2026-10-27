"use client";

import { useParams } from "next/navigation";
import { ExperimentView, isFinished } from "@/components/experiment-view";
import { LoadState } from "@/components/load-state";
import type { Experiment } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

const POLL_MS = 1500;

export function ExperimentLoader() {
  const { id } = useParams<{ id: string }>();
  // Poll until the experiment reaches a final state (done, capped or error).
  const state = useApiData<Experiment>(`/v1/experiments/${id}`, (e) => (isFinished(e) ? null : POLL_MS));
  return <LoadState state={state}>{(experiment) => <ExperimentView experiment={experiment} />}</LoadState>;
}
