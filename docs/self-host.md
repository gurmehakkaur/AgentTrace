# Running AgentTrace yourself

For teams that cannot send traces to a service they do not run. You run the API, the web app and the database; recording and forking your own agents then involve no one else's servers. This guide is written from the code and the deploy file, and has **not** been followed end to end on a clean machine, so treat the first run as a check of the guide as much as of the software. No Docker image or compose file is provided.

## What you need

| Piece | Why | Notes |
| --- | --- | --- |
| A SurrealDB 3.x instance | All runs, steps, experiments, keys, webhooks | Yours. Set `SURREAL_URL` (the bare `wss://` or `ws://` host), `SURREAL_NS`, `SURREAL_DB`, and `SURREAL_USER` and `SURREAL_PASS` (or `SURREAL_TOKEN`). |
| Clerk | People sign in; an organization is a workspace | **Required.** There is no sign-in-free mode. Clerk's own servers see sign-ins. Set `CLERK_ISSUER`, `CLERK_JWKS_URL`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, and enable Organizations. |
| Python 3.11 and Node | The API and the web app | `render.yaml` shows the build and start commands. |
| An Anthropic key | Only for things our server runs itself: the renewal demo, root cause, and the likely cause in an alert | Leave `ANTHROPIC_API_KEY` unset if you only record and fork through your own worker. Root cause then does not work. When it is used, excerpts of a registered workflow's trace go to Anthropic. |
| Agent Memory (`SPECTRON_*`) | Remembers verified failure patterns | Optional. Without it the app runs and simply does not remember. It is a hosted SurrealDB service, so leave it unset to keep everything inside. |

## Steps

```bash
git clone https://github.com/AjayMaan13/AgentTrace && cd AgentTrace
cp .env.example .env            # fill in the names above; ENV=prod, WEB_ORIGINS=<your web address>
python3.11 -m venv api/.venv && api/.venv/bin/pip install ./sdk ./api
api/.venv/bin/python api/scripts/create_workspace_key.py --workspace <your Clerk organization id>   # applies the schema first
cd api && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# in another shell: NEXT_PUBLIC_API_URL is read at BUILD time
cd web && NEXT_PUBLIC_API_URL=https://<your api> npm install && npm run build && npm start
```

The schema is applied by that script (`db.apply_schema()`, idempotent). **Run it again after every upgrade**: new tables arrive with new features (the webhook table is the latest).

## What stays inside

- Traces, state, experiments, keys and webhook addresses live in your database. Secrets are redacted by the SDK before a trace leaves the process, and again on ingest.
- Forking your own agents runs them in your own worker, next to your code. Our server never runs them.
- Calls out of the API: Clerk's key set (to check sign-ins), Anthropic (only as above), Agent Memory (only if set), and the webhook addresses an admin adds.

## Not covered

- No high availability. Experiments registered on the server run inside the API process and do not survive a restart; worker jobs do (they sit in the database and a lease expires).
- Rate limits are in memory, per process. Put a reverse proxy with its own limits and a request size cap in front.
- No retention sweep: deleting data is by an admin, by hand.
- See `SECURITY.md` for the known gaps.

## Speed, and the free-plan sleep

- **Database connections are reused.** Measured against SurrealDB Cloud: opening a connection takes about 0.4 s, *closing* one about 1 s, and a query about 0.06 s, so a request that opened and closed its own connection spent over 90% of its time on that. The running API now keeps up to 4 idle connections (never shared by two callers at once; one that raised is thrown away; one idle for 15 s is checked first; an open that times out is tried once more). Health check: 1.55 s to 0.05 s. First load of the public demo data: 13 s to 0.4 s. A worker job: 21 s to 1.5 s. Set `SURREAL_POOL=0` to turn it off.
- **The public `/demo` page** tries the API for 4 seconds and otherwise shows a saved copy of the same stored results (`web/lib/demo-snapshot.ts`). Regenerate it after the demo data changes: `node web/scripts/snapshot-demo.mjs https://<your-api>`.
- **What code cannot fix:** a Render free-plan service goes to sleep after about 15 minutes without traffic and takes about 50 seconds to wake. Two services in a row (the web app, then the API it calls) is the two-minute wait. Either upgrade both to a paid plan that does not sleep (a billing decision in the Render dashboard, or `plan:` in `render.yaml`), or send a request to each every ten minutes from an uptime service while judging is open. Free services share a monthly allowance of instance hours, so keeping both awake for weeks will run out; for a few days it is fine. Before presenting or recording, open both once and wait for an answer.
