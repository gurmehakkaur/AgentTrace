"""Tell people when a run fails: a message to Slack or to any address that accepts a JSON post.

When a run finishes with a wrong answer (or an error) and the workspace has webhooks, each one gets the workflow,
a link, the reason the owner's check gave, and, if that webhook asked for it, the most likely cause.

The likely cause costs tokens and nobody is there to approve it, so it is opt-in per webhook, it runs under the
same per-minute limit as a person starting one (charged to `webhook:<id>`), and it only exists for workflows
registered on this server. Otherwise the alert says why there is no suspect.

An address a workspace admin types in is a request our server makes, so it is checked twice, when it is saved and
when it is used: https only, the standard port, no user name in it, and the host must resolve only to public
addresses (never loopback, a private network, link-local or the cloud metadata address). Slack addresses must be
hooks.slack.com. Redirects are not followed. The connection goes to the very address that passed the check, with
the certificate checked against the name, so a name cannot be swung to a private address in between (DNS rebinding).

A run alerts once, however many times its finish is sent. A workspace is limited to 10 alerts a minute.
Run text is escaped for Slack, so a run cannot mention a channel or plant a link in the message.
"""

import asyncio
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import socket
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException

from app import db
from app.config import get_settings
from app.security import audit
from app.security.limits import alert_limiter
from app.workflows.registry import REGISTRY

log = logging.getLogger(__name__)

SLACK_HOST = "hooks.slack.com"
TIMEOUT_S = 5.0
KINDS = ("slack", "generic")


class _Pinned(http.client.HTTPSConnection):
    """An https connection that goes to an address we already checked, not to whatever the name means by now."""

    def __init__(self, host: str, ip: str) -> None:
        super().__init__(host, timeout=TIMEOUT_S)
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port or 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # the certificate is checked against the NAME


def _public_ip(host: str) -> str:
    """The first address of `host`, if every address it has is public. ValueError otherwise."""
    try:
        found = [i[4][0] for i in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    except OSError:
        raise ValueError("That address cannot be found.") from None
    if not found or any(not ipaddress.ip_address(a).is_global for a in found):
        raise ValueError("That address is on a private network, so it is not allowed.")
    return found[0]


def validate(url: str, kind: str) -> str:
    """The host if the address is acceptable, else a ValueError saying why in plain words. Blocking (it resolves
    the name): call it through `check` from async code."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("Use an https address.")
    if parts.username or parts.password:
        raise ValueError("The address cannot contain a user name or password.")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("The address has a bad port.") from None
    if port not in (None, 443):
        raise ValueError("Only the standard https port is allowed.")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("The address has no host.")
    if kind == "slack":
        if host != SLACK_HOST or not parts.path.startswith("/services/"):
            raise ValueError("A Slack address looks like https://hooks.slack.com/services/...")
        return host
    try:
        if not ipaddress.ip_address(host).is_global:  # an address written out, such as 127.0.0.1 or [::1]
            raise ValueError("That address is on a private network, so it is not allowed.")
    except ValueError as exc:
        if "private network" in str(exc):
            raise
        _public_ip(host)  # a name: every address it resolves to must be public
    return host


async def check(url: str, kind: str) -> str:
    return await asyncio.to_thread(validate, url, kind)


def _escape(text: Any) -> str:
    """Slack treats & < > as markup: <!channel> pings everyone and <https://x|y> makes a link."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clip(text: Any, n: int) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def event_for(run: dict[str, Any], suspect: dict[str, Any] | None, note: str | None) -> dict[str, Any]:
    origin = get_settings().web_origins[0]
    verdict = (run.get("oracle_detail") or {}).get("verdict") or {}
    return {
        "event": "run.failed",
        "run": {"id": run["id"], "workflow": run["workflow"], "outcome": run["outcome"], "started_at": run.get("started_at"),
                "url": f"{origin}/runs/{run['id']}"},
        "check": {"name": verdict.get("name"), "reason": _clip(verdict["reason"], 300)} if verdict.get("reason") else None,
        "suspect": suspect,
        "suspect_note": note,
    }


def slack_message(event: dict[str, Any]) -> dict[str, Any]:
    r = event["run"]
    what = "ended in an error" if r["outcome"] == "error" else "gave a wrong answer"
    lines = [f"*{_escape(r['workflow'])}* {what}."]
    if event["check"]:
        lines.append(f"Check {_escape(event['check']['name'])}: {_escape(event['check']['reason'])}")
    s = event["suspect"]
    if s:
        lines.append(f"Most likely cause: the *{_escape(s['agent'])}* ({round(s['confidence'] * 100)}%). {_escape(s['hypothesis'])}")
    elif event["suspect_note"]:
        lines.append(_escape(event["suspect_note"]))
    lines.append(f"<{r['url']}|Open the run>")  # the one link in the message is ours
    return {"text": "\n".join(lines)}


def _post_sync(url: str, body: bytes, headers: dict[str, str]) -> int:
    """Post once. The name is resolved here, checked, and the connection goes to that very address, so it cannot be
    swung to a private one between the check and the connection. A redirect is an answer like any other: not followed."""
    parts = urlsplit(url)
    conn = _Pinned(parts.hostname or "", _public_ip(parts.hostname or ""))
    try:
        conn.request("POST", (parts.path or "/") + (f"?{parts.query}" if parts.query else ""), body, {"Content-Type": "application/json", **headers})
        resp = conn.getresponse()
        resp.read(1024)  # the answer is not used, and a big one is not read
        return resp.status
    finally:
        conn.close()


async def deliver(hook: dict[str, Any], payload: dict[str, Any]) -> int | None:
    """Post once, and once more if it could not connect. Returns the HTTP status, or None if it never got through."""
    try:
        await check(hook["url"], hook["kind"])  # again now: the name may have moved since it was saved
    except ValueError as exc:
        log.warning("webhook %s not sent: %s", hook.get("id"), exc)
        return None
    body = json.dumps(payload, default=str).encode()
    headers = {}
    if hook["kind"] == "generic" and hook.get("secret"):
        headers["X-AgentTrace-Signature"] = "sha256=" + hmac.new(hook["secret"].encode(), body, hashlib.sha256).hexdigest()
    for attempt in (1, 2):
        try:
            return await asyncio.to_thread(_post_sync, hook["url"], body, headers)
        except ValueError as exc:  # the name now points somewhere it must not
            log.warning("webhook %s not sent: %s", hook.get("id"), exc)
            return None
        except (TimeoutError, OSError, http.client.HTTPException):
            if attempt == 2:
                return None
            await asyncio.sleep(1)
    return None


async def _suspect(workspace: str, run: dict[str, Any], hooks: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """The most likely cause, if some webhook asked for it and the server can find one."""
    asking = next((h for h in hooks if h.get("include_suspect")), None)
    if asking is None:
        return None, None
    if run["outcome"] != "fail" or run["workflow"] not in REGISTRY:
        return None, "A likely cause is only worked out for runs of workflows registered on the server."
    from app.rca.report import report_view  # noqa: PLC0415
    from app.routes.rca import run_rca  # noqa: PLC0415
    from app.runtime import get_runtime  # noqa: PLC0415

    try:
        stored = await db.get_latest_rca_report(workspace, run["id"])
        report = report_view(stored) if stored else await run_rca(workspace, f"webhook:{asking['id']}", run["id"], get_runtime())
    except Exception as exc:  # the alert still goes out, without a suspect
        log.warning("alert for %s: no suspect (%s)", run["id"], type(exc).__name__)
        return None, "A likely cause could not be worked out for this run."
    if not report["candidates"]:
        return None, "No likely cause was found."
    top = max(report["candidates"], key=lambda c: c["confidence"])
    agent = next((s["agent"] for s in run["steps"] if s["node_run_idx"] == top["node_run_idx"]), f"turn {top['node_run_idx']}")
    return {"node_run_idx": top["node_run_idx"], "agent": agent, "confidence": top["confidence"],
            "hypothesis": _clip(top["hypothesis"], 400)}, None


async def notify_failure(workspace: str, run_id: str) -> None:
    """Alert every webhook of the workspace about a failed run. Never raises: a failed alert must not fail a run."""
    try:
        hooks = [h for h in await db.list_webhooks(workspace) if not h.get("revoked_at")]
        if not hooks or not await db.claim_alert(workspace, run_id):
            return
        try:
            alert_limiter.check(workspace)
        except HTTPException:
            log.warning("alert for %s dropped: too many alerts this minute", run_id)
            return
        run = await db.get_run_with_steps(workspace, run_id)
        if run is None or run.get("outcome") not in ("fail", "error"):
            return
        suspect, note = await _suspect(workspace, run, hooks)
        for hook in hooks:
            wants = bool(hook.get("include_suspect"))
            event = event_for(run, suspect if wants else None, note if wants else None)
            status = await deliver(hook, slack_message(event) if hook["kind"] == "slack" else event)
            ok = status is not None and 200 <= status < 300
            await audit.record(workspace, f"webhook:{hook['id']}", "alert.sent" if ok else "alert.failed", run_id, {"status": status})
    except Exception as exc:
        log.warning("alert for %s failed: %s", run_id, type(exc).__name__)


def fork_words(control: dict[str, Any], treatment: dict[str, Any], p: float | None) -> str:
    """What a finished fork says, in plain words, and never more than the numbers can support."""
    if not treatment["total"] or not control["total"]:
        return "It finished without enough runs to say anything."
    c, t = control["pass"] / control["total"], treatment["pass"] / treatment["total"]
    if t > c:
        if p is not None and p < 0.05:
            return "The change fixed it." if t >= 0.8 else "The change helped, but not every run came out right."
        return "It looks like the change helped, but there are too few runs to be sure."
    if t == c:
        return "The change made no difference."
    return "The change made things worse."


def fork_event(workflow: str, agent: str, exp: dict[str, Any]) -> dict[str, Any]:
    origin = get_settings().web_origins[0]
    stats = exp.get("stats") or {}
    return {
        "event": "experiment.finished",
        "experiment": {"id": exp["id"], "status": exp["status"], "workflow": workflow, "changed_agent": agent, "n": exp["n"],
                       "without_the_change": exp["control"], "with_the_change": exp["treatment"], "fisher_p": stats.get("fisher_p"),
                       "label": stats.get("label", "directional"), "url": f"{origin}/runs/{exp['parent_run']}?fork={exp['id']}",
                       "summary": fork_words(exp["control"], exp["treatment"], stats.get("fisher_p"))},
    }


def slack_fork_message(event: dict[str, Any]) -> dict[str, Any]:
    e = event["experiment"]
    c, t = e["without_the_change"], e["with_the_change"]
    lines = [f"*Fork finished* on *{_escape(e['workflow'])}*: changing the *{_escape(e['changed_agent'])}*."]
    lines.append(f"Without the change {c['pass']} of {c['total']} right, with it {t['pass']} of {t['total']}. {_escape(e['summary'])}")
    p = e["fisher_p"]
    lines.append(f"Directional only ({'p < 0.001' if p is not None and p < 0.001 else f'p = {p:.3f}' if p is not None else 'no p-value yet'}): live steps are sampled.")
    if e["status"] == "capped":
        lines.append("It stopped early at the token ceiling.")
    lines.append(f"<{e['url']}|Open it>")
    return {"text": "\n".join(lines)}


async def notify_experiment(workspace: str, experiment_id: str) -> None:
    """Tell every webhook that wants to know that a fork finished. Never raises."""
    try:
        hooks = [h for h in await db.list_webhooks(workspace) if not h.get("revoked_at") and h.get("on_forks", True)]
        if not hooks:
            return
        exp = await db.get_experiment(workspace, experiment_id)
        if exp is None or exp["status"] not in ("done", "capped"):
            return
        try:
            alert_limiter.check(workspace)
        except HTTPException:
            log.warning("fork alert for %s dropped: too many alerts this minute", experiment_id)
            return
        parent = await db.get_run_with_steps(workspace, exp["parent_run"])
        agents = await db.agents_for_runs([exp["parent_run"]])
        event = fork_event(parent["workflow"] if parent else "a workflow", agents.get(exp["parent_run"], {}).get(exp["fork_idx"], "an agent"), {**exp, "id": experiment_id})
        for hook in hooks:
            status = await deliver(hook, slack_fork_message(event) if hook["kind"] == "slack" else event)
            ok = status is not None and 200 <= status < 300
            await audit.record(workspace, f"webhook:{hook['id']}", "alert.sent" if ok else "alert.failed", experiment_id, {"status": status, "about": "fork"})
    except Exception as exc:
        log.warning("fork alert for %s failed: %s", experiment_id, type(exc).__name__)
