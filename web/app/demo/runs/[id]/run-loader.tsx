"use client";

import { useParams } from "next/navigation";
import { LoadState } from "@/components/load-state";
import { RunView } from "@/components/run-view";
import { usePublicData } from "@/lib/use-public-data";
import type { Run } from "@/lib/types";

export function DemoRunLoader() {
  const { id } = useParams<{ id: string }>();
  const state = usePublicData<Run>(`/v1/public/demo/runs/${id}`);
  return (
    <LoadState state={state} notFound="That run is not part of the demo.">
      {(run) => <RunView run={run} mode="demo" />}
    </LoadState>
  );
}
