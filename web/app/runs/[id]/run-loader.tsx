"use client";

import { useParams } from "next/navigation";
import { LoadState } from "@/components/load-state";
import { RunView } from "@/components/run-view";
import type { Run } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

export function RunLoader() {
  const { id } = useParams<{ id: string }>();
  const state = useApiData<Run>(`/v1/runs/${id}`);
  return <LoadState state={state}>{(run) => <RunView run={run} />}</LoadState>;
}
