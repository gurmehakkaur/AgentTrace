"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, useApi } from "@/lib/api";

/** Copies the saved example into this workspace, so there is a real run to open and fork straight away.
 * It makes no model calls and costs nothing. */
export function SampleRunButton({ primary = true }: { primary?: boolean }) {
  const api = useApi();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const { id } = await api<{ id: string }>("/v1/runs/sample", { method: "POST" });
      router.push(`/runs/${id}`);
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <button type="button" className={primary ? "btn btn-primary" : "btn"} onClick={add} disabled={busy}>
        {busy ? "Adding it…" : "Add the saved example to my workspace"}
      </button>
      {error && <p role="alert" className="text-bad">{error}</p>}
    </div>
  );
}
