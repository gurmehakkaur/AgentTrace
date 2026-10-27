"use client";

import { useState } from "react";
import { ApiError, useApi } from "@/lib/api";
import { useApiData } from "@/lib/use-api-data";

type Hook = { id: string; kind: "slack" | "generic"; host: string; ends: string; include_suspect: boolean; on_forks?: boolean; created_at?: string; revoked_at?: string | null };

/** Tell people when a run fails. Admins add a Slack address (or any address that takes a JSON post). */
export function Alerts() {
  const api = useApi();
  const [tick, setTick] = useState(0);
  const hooks = useApiData<Hook[]>(`/v1/webhooks?k=${tick}`);
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<"slack" | "generic">("slack");
  const [suspect, setSuspect] = useState(false);
  const [forks, setForks] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<string, string>>({});

  async function add() {
    setBusy(true);
    setError(null);
    setSecret(null);
    try {
      const made = await api<{ secret?: string }>("/v1/webhooks", { method: "POST", body: JSON.stringify({ url: url.trim(), kind, include_suspect: suspect, on_forks: forks }) });
      setSecret(made.secret ?? null);
      setUrl("");
      setTick((t) => t + 1);
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    try {
      await api(`/v1/webhooks/${id}`, { method: "DELETE" });
      setTick((t) => t + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }
  async function test(id: string) {
    setTested((t) => ({ ...t, [id]: "Sending…" }));
    try {
      const r = await api<{ delivered: boolean; status: number | null }>(`/v1/webhooks/${id}/test`, { method: "POST" });
      setTested((t) => ({ ...t, [id]: r.delivered ? "Delivered. Look in your channel." : `Not delivered${r.status ? ` (the address answered ${r.status})` : ""}.` }));
    } catch (err) {
      setTested((t) => ({ ...t, [id]: err instanceof Error ? err.message : "Request failed" }));
    }
  }

  if (hooks.status === "error" && hooks.code === 403) return null; // admins only, and the keys section already says so
  const live = hooks.status === "ok" ? hooks.data.filter((h) => !h.revoked_at) : [];
  return (
    <section className="flex flex-col gap-4" aria-label="Failure alerts">
      <div>
        <h2 className="font-serif text-2xl">Get told when a run fails</h2>
        <p className="mt-1 max-w-[60ch] text-muted">
          When a run comes out wrong, we post a message with the workflow, the reason your check gave and a link to the run. When a fork finishes, we post what changed and the result. Add a Slack
          address, or any address that takes a JSON post (we sign it, so you can tell it came from us). The address is a secret: we show
          only its host and last four characters afterwards.
        </p>
      </div>
      <div className="flex max-w-xl flex-col gap-3">
        <label htmlFor="hook-url" className="font-medium">Address</label>
        <input id="hook-url" value={url} onChange={(e) => setUrl(e.target.value)} autoComplete="off" spellCheck={false}
          placeholder={kind === "slack" ? "https://hooks.slack.com/services/…" : "https://example.com/agenttrace"}
          className="rounded-lg border border-line bg-tile px-3 py-2" />
        <div className="flex flex-wrap gap-4">
          <label className="flex items-center gap-2"><input type="radio" name="hook-kind" checked={kind === "slack"} onChange={() => setKind("slack")} /> Slack</label>
          <label className="flex items-center gap-2"><input type="radio" name="hook-kind" checked={kind === "generic"} onChange={() => setKind("generic")} /> Any address</label>
        </div>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={forks} onChange={(e) => setForks(e.target.checked)} />
          <span>Also tell me when a fork finishes, with what changed and how many runs came out right. <span className="text-muted">One message per fork, however many runs it made. The result is directional.</span></span>
        </label>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={suspect} onChange={(e) => setSuspect(e.target.checked)} />
          <span>Also say which step most likely broke it. <span className="text-muted">This costs tokens for each failed run of a workflow registered on our server, within the usual limits. For your own workflows the message carries your check&apos;s reason instead.</span></span>
        </label>
        <div><button type="button" className="btn btn-primary" onClick={add} disabled={busy || url.trim().length < 12}>{busy ? "Adding…" : "Add"}</button></div>
        {error && <p role="alert" className="text-bad">{error}</p>}
        {secret && (
          <div className="card flex flex-col gap-2 p-4">
            <p className="font-medium text-good">Signing secret. It will not be shown again.</p>
            <code className="block rounded-lg bg-tile p-3 font-mono text-[0.8125rem] [overflow-wrap:anywhere]">{secret}</code>
            <p className="text-[0.8125rem] text-muted">Each post carries <code>X-AgentTrace-Signature: sha256=…</code>, an HMAC of the body with this secret.</p>
          </div>
        )}
      </div>
      {live.length > 0 && (
        <ul className="card divide-y divide-line">
          {live.map((h) => (
            <li key={h.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <span className="font-medium">{h.kind === "slack" ? "Slack" : "Any address"}</span>
              <code className="font-mono text-[0.8125rem]">{h.host}/…{h.ends}</code>
              {h.on_forks !== false && <span className="text-[0.8125rem] text-muted">failed runs and finished forks</span>}
              {h.on_forks === false && <span className="text-[0.8125rem] text-muted">failed runs only</span>}
              {h.include_suspect && <span className="text-[0.8125rem] text-muted">with the likely cause</span>}
              <span className="text-[0.8125rem] text-muted">{tested[h.id]}</span>
              <button type="button" className="btn ml-auto" onClick={() => test(h.id)}>Send a test</button>
              <button type="button" className="btn" onClick={() => remove(h.id)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
