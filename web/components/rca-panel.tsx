"use client";

import { useEffect, useState } from "react";
import { RcaView } from "@/components/rca-view";
import { ApiError, useApi } from "@/lib/api";
import type { Candidate, RcaReport, Run } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

export function RcaPanel({
  run, onTest, onReport,
}: { run: Run; onTest: (candidate: Candidate) => void; onReport?: (report: RcaReport | null) => void }) {
  const api = useApi();
  const stored = useApiData<RcaReport>(`/v1/runs/${run.id}/rca`); // 404 just means "not run yet"
  const [fresh, setFresh] = useState<RcaReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const agents = new Map(run.steps.map((s) => [s.node_run_idx, s.agent]));
  const report = fresh ?? (stored.status === "ok" ? stored.data : null);
  const storedProblem =
    stored.status === "error" && stored.code !== 404 ? `Could not load the saved analysis: ${stored.message}` : null;

  // Tell the page what the report says, so the agent cards can mark the likely cause.
  useEffect(() => {
    onReport?.(report);
  }, [report, onReport]);

  // While verification runs in the background, re-read the report until it finishes.
  const verifying = report?.verification?.status === "running";
  useEffect(() => {
    if (!verifying) return;
    const timer = setInterval(() => {
      api<RcaReport>(`/v1/runs/${run.id}/rca`).then(setFresh).catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
  }, [verifying, api, run.id]);

  async function verify() {
    setVerifyBusy(true);
    setError(null);
    try {
      await api(`/v1/runs/${run.id}/rca/verify`, { method: "POST" });
      setFresh(await api<RcaReport>(`/v1/runs/${run.id}/rca`));
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
    } finally {
      setVerifyBusy(false);
    }
  }

  async function find() {
    setBusy(true);
    setError(null);
    try {
      setFresh(await api<RcaReport>(`/v1/runs/${run.id}/rca`, { method: "POST" }));
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <RcaView
      report={report}
      agentOf={(i) => agents.get(i) ?? "?"}
      canRun={run.outcome === "fail"}
      busy={busy}
      error={error ?? storedProblem}
      onFind={find}
      onTest={onTest}
      experimentHref={(id) => `/experiments/${id}`}
      onVerify={verify}
      verifyBusy={verifyBusy}
    />
  );
}
