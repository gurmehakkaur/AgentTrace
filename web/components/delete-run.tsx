"use client";

import { useOrganization } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, useApi } from "@/lib/api";

/** Admins only (the API enforces it; this just keeps the button out of everyone else's way). */
export function DeleteRun({ runId }: { runId: string }) {
  const { membership } = useOrganization();
  const router = useRouter();
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (membership?.role !== "org:admin") return null;

  async function remove() {
    const sure = window.confirm(
      "Delete this run, every fork of it, their experiments, root-cause reports and remembered patterns? This cannot be undone.",
    );
    if (!sure) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/runs/${runId}`, { method: "DELETE" });
      router.push("/runs");
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={remove}
        disabled={busy}
        className="btn border-bad/40 text-bad hover:bg-bad-tint"
      >
        {busy ? "Deleting…" : "Delete run"}
      </button>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
    </div>
  );
}
