"""In-memory stand-in for the parts of app.db that routes and forks use (fast, offline)."""

import copy
from datetime import UTC, datetime
from typing import Any

from app import db


class FakeDB:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.steps: dict[tuple[str, int], dict[str, Any]] = {}
        self.forks: list[dict[str, Any]] = []
        self.experiments: dict[str, dict[str, Any]] = {}
        self.tested: list[tuple[str, str]] = []
        self.rca_reports: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self.benchmarks: list[dict[str, Any]] = []
        self.fail_audit = False
        self.api_keys: list[dict[str, Any]] = []
        self.webhooks: dict[str, dict[str, Any]] = {}

    def session(self):
        """No connection to share here; the same block, so code under test runs as it does for real."""
        from contextlib import asynccontextmanager  # noqa: PLC0415

        @asynccontextmanager
        async def noop():
            yield
        return noop()

    async def key_for_hash(self, h):
        for k in self.api_keys:
            if k["sha256"] == h and not k.get("revoked_at"):
                return {"id": k["id"], "workspace": k["workspace"], "scopes": k["scopes"]}
        if h in self.keys and not any(k["sha256"] == h for k in self.api_keys):  # a key seeded straight into the store
            return {"id": "seeded", "workspace": self.keys[h], "scopes": ["ingest"]}
        return None

    async def create_webhook(self, ws, doc):
        hook_id = f"w{len(self.webhooks) + 1}"
        self.webhooks[hook_id] = {**doc, "id": hook_id, "workspace": ws, "created_at": f"2026-01-01T00:00:{len(self.webhooks):02d}"}
        return hook_id

    async def list_webhooks(self, ws):
        return [copy.deepcopy(h) for h in reversed(list(self.webhooks.values())) if h["workspace"] == ws]

    async def revoke_webhook(self, ws, webhook_id):
        h = self.webhooks.get(webhook_id)
        if not h or h["workspace"] != ws or h.get("revoked_at"):
            return False
        h["revoked_at"] = "now"
        return True

    async def claim_alert(self, ws, run_id):
        r = self.runs.get(run_id)
        if not r or r["workspace"] != ws or r.get("alerted_at"):
            return False
        r["alerted_at"] = "now"
        return True

    async def upsert_workspace(self, ws, name):
        return None

    async def create_api_key(self, ws, prefix, sha256, created_by, scopes=("ingest",)):
        self.keys[sha256] = ws
        self.api_keys.append({"id": f"k{len(self.api_keys) + 1}", "workspace": ws, "prefix": prefix, "sha256": sha256,
                              "created_by": created_by, "scopes": list(scopes), "created_at": f"2026-01-01T00:00:{len(self.api_keys):02d}"})

    async def list_api_keys(self, ws):
        return [{k: v for k, v in key.items() if k not in ("sha256", "workspace")}
                for key in reversed(self.api_keys) if key["workspace"] == ws]

    async def touch_key(self, key_id):
        for k in self.api_keys:
            if k["id"] == key_id:
                k["last_seen_at"] = datetime.now(UTC).isoformat()

    async def count_workers_since(self, ws, since_iso):
        return sum(1 for k in self.api_keys if k["workspace"] == ws and "worker" in k["scopes"] and not k.get("revoked_at")
                   and k.get("last_seen_at", "") > since_iso)

    async def revoke_api_key(self, ws, key_id):
        for key in self.api_keys:
            if key["id"] == key_id and key["workspace"] == ws and not key.get("revoked_at"):
                key["revoked_at"] = "now"
                return True
        return False

    async def list_experiments(self, ws, limit=200):
        return sorted((e for e in self.experiments.values() if e["workspace"] == ws),
                      key=lambda e: e.get("created_at", ""))[:limit]

    async def create_run(self, ws, run_id, workflow, started_at, kind="recorded"):
        if run_id in self.runs:
            if self.runs[run_id]["workspace"] != ws:
                raise db.RunConflict(run_id)
            return False
        self.runs[run_id] = {"id": run_id, "workspace": ws, "workflow": workflow,
                             "started_at": started_at, "status": "running", "kind": kind}
        return True

    async def run_exists(self, ws, run_id):
        return self.runs.get(run_id, {}).get("workspace") == ws

    async def add_steps(self, ws, run_id, steps):
        added = 0
        for s in steps:
            if (run_id, s["idx"]) not in self.steps:
                self.steps[(run_id, s["idx"])] = s
                added += 1
        return added

    async def finish_run(self, ws, run_id, status, outcome, oracle_detail):
        if not await self.run_exists(ws, run_id):
            return False
        self.runs[run_id].update(status=status, outcome=outcome, oracle_detail=oracle_detail)
        return True

    async def get_run_with_steps(self, ws, run_id):
        if not await self.run_exists(ws, run_id):
            return None
        steps = sorted((s for (r, _), s in self.steps.items() if r == run_id), key=lambda s: s["idx"])
        return {**self.runs[run_id], "steps": steps}

    async def list_runs(self, ws, limit=50, kind=None):
        return sorted((r for r in self.runs.values() if r["workspace"] == ws and (kind is None or r.get("kind") == kind)),
                      key=lambda r: r["started_at"], reverse=True)[:limit]

    async def create_fork_edge(self, ws, fork_run_id, parent_run_id, at_idx, arm, experiment=None):
        if not (await self.run_exists(ws, fork_run_id) and await self.run_exists(ws, parent_run_id)):
            raise LookupError("both runs must exist in the workspace")
        self.forks.append({"fork_run": fork_run_id, "parent": parent_run_id,
                           "at_idx": at_idx, "arm": arm, "experiment": experiment})

    async def list_forks(self, ws, parent_run_id):
        return [f for f in self.forks if f["parent"] == parent_run_id]

    async def create_experiment(self, ws, experiment_id, doc):
        self.experiments[experiment_id] = {**doc, "id": experiment_id, "workspace": ws}

    async def update_experiment(self, ws, experiment_id, merge):
        if self.experiments.get(experiment_id, {}).get("workspace") == ws:
            self.experiments[experiment_id].update(merge)

    async def update_experiment_if_rev(self, ws, experiment_id, rev, merge):
        e = self.experiments.get(experiment_id)
        if not e or e["workspace"] != ws or (e.get("rev") or 0) != rev:
            return False
        e.update(copy.deepcopy(merge))
        return True

    async def get_experiment(self, ws, experiment_id):
        e = self.experiments.get(experiment_id)
        return copy.deepcopy(e) if e and e["workspace"] == ws else None

    async def create_tested_edge(self, experiment_id, run_id):
        self.tested.append((experiment_id, run_id))

    async def get_run_summary(self, ws, run_id):
        r = self.runs.get(run_id)
        if not r or r["workspace"] != ws:
            return None
        steps = [s for (rid, _), s in self.steps.items() if rid == run_id]
        return {"status": r.get("status"), "outcome": r.get("outcome"),
                "tokens_in": sum(s["tokens_in"] for s in steps),
                "tokens_out": sum(s["tokens_out"] for s in steps)}

    async def create_benchmark(self, ws, benchmark_id, doc):
        self.benchmarks.append({**doc, "id": benchmark_id, "workspace": ws})

    async def get_benchmark_for_experiment(self, ws, experiment_id):
        mine = [b for b in self.benchmarks if b["workspace"] == ws and b["experiment"] == experiment_id]
        return max(mine, key=lambda b: b["created_at"]) if mine else None

    async def create_audit(self, ws, doc):
        if self.fail_audit:
            raise RuntimeError("audit store down")
        self.audit.append({**doc, "workspace": ws})

    async def list_audit(self, ws, limit=100):
        return sorted((a for a in self.audit if a["workspace"] == ws), key=lambda a: a["at"], reverse=True)[:limit]

    async def count_experiments_since(self, created_by, since_iso):
        return sum(1 for e in self.experiments.values() if e.get("created_by") == created_by and e["created_at"] >= since_iso)

    async def delete_run_cascade(self, ws, run_id):
        if not await self.run_exists(ws, run_id):
            return None
        ids, frontier = [run_id], [run_id]
        while frontier:
            frontier = [f["fork_run"] for f in self.forks if f["parent"] in frontier and f["fork_run"] not in ids]
            ids += frontier
        exps = {i: e for i, e in self.experiments.items() if e["workspace"] == ws and e["parent_run"] in ids}
        steps = [k for k in self.steps if k[0] in ids]
        reports = [r for r in self.rca_reports if r["workspace"] == ws and r["run"] in ids]
        out = {"runs": len(ids), "steps": len(steps), "experiments": len(exps), "rca_reports": len(reports),
               "run_ids": ids, "memory_scopes": sorted({e["memory_scope"] for e in exps.values() if e.get("memory_scope")})}
        for k in steps:
            del self.steps[k]
        self.benchmarks = [b for b in self.benchmarks if b["experiment"] not in exps]
        for i in exps:
            del self.experiments[i]
        self.tested = [t for t in self.tested if t[0] not in exps and t[1] not in ids]
        self.forks = [f for f in self.forks if f["fork_run"] not in ids and f["parent"] not in ids]
        self.rca_reports = [r for r in self.rca_reports if r not in reports]
        for r in ids:
            del self.runs[r]
        return out

    async def list_memory_scopes(self, ws, limit=50):
        return list(dict.fromkeys(e["memory_scope"] for e in self.experiments.values()
                                  if e["workspace"] == ws and e.get("remembered") and e.get("memory_scope")))

    async def clear_featured(self, ws):
        for r in self.runs.values():
            if r["workspace"] == ws:
                r["featured"] = False
        for e in self.experiments.values():
            if e["workspace"] == ws:
                e["featured"] = False

    async def set_run_featured(self, ws, run_id):
        if await self.run_exists(ws, run_id):
            self.runs[run_id]["featured"] = True

    async def get_featured_run_id(self, ws):
        mine = [r for r in self.runs.values() if r["workspace"] == ws and r.get("featured")]
        return max(mine, key=lambda r: r["started_at"])["id"] if mine else None

    async def list_featured_experiments(self, ws):
        return [{**e} for e in self.experiments.values() if e["workspace"] == ws and e.get("featured")]

    async def agents_for_runs(self, run_ids):
        out: dict = {}
        for (run, _), s in self.steps.items():
            if run in set(run_ids):
                out.setdefault(run, {})[s["node_run_idx"]] = s["agent"]
        return out

    async def list_experiments_for_runs(self, ws, run_ids):
        mine = [{**e} for e in self.experiments.values() if e["workspace"] == ws and e["parent_run"] in set(run_ids)]
        return sorted(mine, key=lambda e: e.get("created_at", ""))

    async def list_experiments_for_run(self, ws, run_id):
        mine = [{**e} for e in self.experiments.values() if e["workspace"] == ws and e["parent_run"] == run_id]
        return sorted(mine, key=lambda e: e.get("created_at", ""))

    async def create_rca_report(self, ws, report_id, doc):
        self.rca_reports.append({**doc, "id": report_id, "workspace": ws})

    async def update_rca_report(self, ws, report_id, merge):
        for r in self.rca_reports:
            if r["id"] == report_id and r["workspace"] == ws:
                r.update(merge)

    async def get_latest_rca_report(self, ws, run_id):
        mine = [r for r in self.rca_reports if r["workspace"] == ws and r["run"] == run_id]
        return max(mine, key=lambda r: r["created_at"]) if mine else None


DB_FUNCTIONS = ("session", "touch_key", "count_workers_since", "upsert_workspace", "create_api_key", "list_api_keys", "revoke_api_key", "list_experiments", "key_for_hash", "create_run", "run_exists", "add_steps", "finish_run",
                "get_run_with_steps", "list_runs", "create_fork_edge", "list_forks",
                "create_experiment", "update_experiment", "update_experiment_if_rev", "create_webhook", "list_webhooks", "revoke_webhook", "claim_alert", "get_experiment", "create_tested_edge",
                "get_run_summary", "create_rca_report", "get_latest_rca_report", "clear_featured", "set_run_featured",
                "get_featured_run_id", "list_featured_experiments", "list_experiments_for_run", "list_experiments_for_runs", "agents_for_runs", "list_memory_scopes", "create_audit", "list_audit",
                "count_experiments_since", "delete_run_cascade", "update_rca_report",
                "create_benchmark", "get_benchmark_for_experiment")
