# AgentTrace — context for the coding assistant

## What we are building
A debugger for multi-agent LLM workflows. It records a run (prompts, tool calls,
payloads, state transitions), lets an engineer edit one step, fork, and replay the
rest live N times in a control arm (no edit) and a treatment arm (edit), then
reports success rates (e.g. 0/5 -> 4/5). A root-cause (RCA) agent ranks suspect steps.

## Non-negotiable wording and semantics
- Recorded steps replay exactly (read from the DB, no API calls).
- Forked steps re-run live. NEVER describe live steps as deterministic.
- Results are shown as k/N per arm plus a Fisher exact p-value, labelled "directional".

## Stack (do not add frameworks without asking)
- api/: Python 3.11, FastAPI, Pydantic v2, anthropic (AsyncAnthropic), surrealdb (Python SDK,
  includes the Agent Memory client), httpx, pytest. No LangChain/LangGraph.
- web/: Next.js (App Router, TypeScript), Clerk, Tailwind. No other UI kit unless asked.
- Hosting: Render (render.yaml). DB: SurrealDB Cloud. No local DB, no local models
  (dev machine is an 8 GB MacBook Air M1).

## Models
- Demo agents: claude-haiku-5-5. It rejects non-default temperature, so sampling is the API default and
  `output_config.effort` (DEMO_EFFORT in config.py) is the control we set.
- RCA agent: claude-haiku-5-5 (user's choice: smaller than sonnet-5-5), forced tool call
  `report_candidates` (verified to work on haiku-5-5; sonnet-5-5 rejects forced tool_choice).
- Model ids live in api/app/config.py only.

## Rules
- Workspace isolation: workspace_id comes ONLY from the verified Clerk JWT (or the
  hashed ingest API key). Never from request bodies. Every query filters on it.
- Redact before persisting. Never log raw prompts or secrets.
- Tools declare side_effect; side-effecting tools must not run live in a fork without a mock.
- Every phase ends with tests that prove its "Done when" criteria. Write them.
- Small commits. Ask before deleting files or changing the data model.
- If an external API shape is uncertain (Clerk claims, Era endpoints, SurrealDB SDK),
  say so and write a tiny probe script instead of guessing.

## Repo notes
- Source of truth for scope and phases: `docs/project-map.md` (project map; `README.md` is the public readme) and `AgentTrace-Build-Guide.md`.
- One `.env` at the repo root (gitignored). `.env.example` lists names only. api loads it with
  python-dotenv, web with `@next/env` (see `web/next.config.ts`). Real env vars win over the file.
- api dev: `cd api && python3.11 -m venv .venv && .venv/bin/pip install -e ../sdk -e '.[dev]' && .venv/bin/pytest`
  (live DB tests: `RUN_LIVE=1 .venv/bin/pytest tests/test_db_live.py`; schema: `api/schema.surql`)
- sdk tests: `api/.venv/bin/pytest sdk/` (stdlib-only package, no install needed; `sdk/pyproject.toml` sets pythonpath)
- web dev: `cd web && npm install && npm run dev`
- web/AGENTS.md says this Next.js has breaking changes: read `web/node_modules/next/dist/docs/` before
  writing Next code.
