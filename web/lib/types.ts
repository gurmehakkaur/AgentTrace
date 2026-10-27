// Shapes returned by the AgentTrace API (api/app/routes, api/app/db.py).

export type Origin = "recorded" | "replayed" | "edited" | "live";
export type Outcome = "pass" | "fail" | "error";
export type State = Record<string, unknown>;

export type Step = {
  run: string;
  idx: number; // 1-based position in the run
  node_run_idx: number; // 1-based: which execution of an agent this step belongs to
  agent: string;
  kind: "llm" | "tool";
  origin: Origin;
  model: string | null;
  params: Record<string, unknown>;
  input: unknown;
  output: unknown;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tool_result: unknown;
  side_effect: boolean | null;
  state_after: State | null; // only on the last step of a node run
  reads: string[];
  writes: string[];
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  redactions: { path: string; type: string }[];
};

export type RunSummary = {
  id: string;
  workflow: string;
  kind: string; // "recorded" | "fork"
  status: string; // running | ok | error
  outcome?: Outcome;
  started_at: string;
  ended_at?: string;
  tokens_in?: number;
  tokens_out?: number;
};

export type OracleDetail = {
  truth?: { open_tickets?: number; open_pipeline_usd?: number };
  footer?: { open_tickets?: number; open_pipeline_usd?: number; risk?: string } | null;
  open_tickets_ok?: boolean;
  pipeline_ok?: boolean;
  critic_loop_ok?: boolean;
  // A check the run's owner wrote in code (any workflow). passed is null when the check itself failed to run.
  verdict?: { kind: "code"; name: string; passed: boolean | null; reason: string };
};

export type Run = RunSummary & {
  oracle_detail?: OracleDetail; steps: Step[];
  forkable?: boolean; // false = view only
  fork_mode?: "server" | "worker" | null; // who re-runs a fork: this server, or the owner's own worker
};

export type Tile = {
  arm: "control" | "treatment";
  i: number;
  status: "queued" | "running" | "done" | "skipped";
  run_id: string | null;
  outcome: Outcome | null;
};

export type Arm = { pass: number; total: number };

export type BenchmarkArm = { pass: number; total: number; errors: number };

// Generalization benchmark: whole fresh runs on other accounts, original vs patched prompt.
export type Benchmark = {
  n: number;
  created_at: string | null;
  excluded_account: string | null; // the account the fix was found on, left out on purpose
  accounts: { account_id: string; original: BenchmarkArm; patched: BenchmarkArm }[];
  totals: { original: Arm; patched: Arm };
};

export type Experiment = {
  id: string;
  status: "queued" | "running" | "done" | "capped" | "error";
  parent_run: string;
  fork_node_run_idx: number;
  n: number;
  edit_patch: State;
  control: Arm;
  treatment: Arm;
  tiles: Tile[];
  stats: {
    fisher_p: number | null;
    wilson: { control: [number, number] | null; treatment: [number, number] | null };
    label: string; // "directional evidence, N=5"
  };
  tokens_used: number;
  token_ceiling: number;
  error: string | null;
  benchmark?: Benchmark | null; // present once a benchmark has been stored for this experiment
  created_at?: string | null; // when the fork was started
  fork_agent?: string | null; // the agent that was changed (set by the forks list)
  workers_online?: number | null; // worker mode: how many of the workspace's workers asked for a job in the last minute
  mode?: "server" | "worker"; // worker: the owner's own worker runs the jobs, and the experiment waits for it
};

export type Candidate = {
  node_run_idx: number;
  step_idx: number;
  confidence: number; // 0..1
  hypothesis: string;
  evidence_quotes: string[]; // checked verbatim against the trace by the API
  proposed_edit: { mode: "output"; patch: State } | null;
  matches_past_pattern: string | null; // experiment id of a recalled, verified pattern this matches
};

/** A past verified root cause recalled from Agent Memory into this analysis. */
export type RecalledPattern = {
  experiment: string;
  run: string | null;
  agent_role: string | null;
  text: string;
  score: number;
};

export type RcaReport = {
  id: string;
  run: string;
  model: string;
  created_at: string;
  lineage: number[]; // node runs on the data path to the failing output
  dropped_quotes: number;
  recalled: RecalledPattern[];
  verification: Verification | null; // auto-verify: the top candidates tested by real experiments
  verdict_idx: number | null; // index (in `candidates`) of the top verified candidate
  verified_by: string[]; // experiment ids that verified a candidate
  tokens_in: number;
  tokens_out: number;
  candidates: Candidate[]; // ranked, most likely first
};

export type VerificationItem = {
  candidate_idx: number;
  experiment_id?: string;
  error?: string; // why this candidate could not be tested
  status?: string;
  control?: Arm;
  treatment?: Arm;
  delta?: number | null; // treatment pass rate minus control pass rate
  verified?: boolean;
};

export type Verification = {
  status: "running" | "done" | "error";
  n: number;
  items: VerificationItem[];
  ranking?: number[]; // candidate indexes, best measured first
  error?: string;
};
