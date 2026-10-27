# AgentTrace web app

The Next.js (App Router) front end: the landing page, the saved example at `/demo`, sign-in with Clerk, and the signed-in
pages (Runs, a Gantt of all runs by time with the forks tried on each, a run as a line of agents, Forks, Activity, Connect your agents).

See the [project README](../README.md) for what AgentTrace is and how to run everything. From this folder:

```bash
npm install
npm run dev     # http://localhost:3000, needs the API at NEXT_PUBLIC_API_URL
npm test        # pure logic: graph, board, verdicts, diffs
npm run build
```

Environment variables live in the single `.env` at the repository root (see `.env.example`). `web/AGENTS.md` notes that this
Next.js version has breaking changes, so read `node_modules/next/dist/docs/` before writing Next code.
