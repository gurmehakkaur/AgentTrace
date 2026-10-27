-- AgentTrace schema. Applied idempotently (OVERWRITE) by db.apply_schema().
-- Tables are SCHEMALESS: Pydantic validates in Python, and only fields we query on are
-- indexed. Text fields are capped at 32 KB by the API layer (later phase), not here.

-- records
DEFINE TABLE OVERWRITE workspace SCHEMALESS;
DEFINE TABLE OVERWRITE api_key SCHEMALESS;
DEFINE INDEX OVERWRITE api_key_sha256 ON api_key FIELDS sha256 UNIQUE;
DEFINE TABLE OVERWRITE workflow SCHEMALESS;
DEFINE TABLE OVERWRITE run SCHEMALESS;
DEFINE INDEX OVERWRITE run_workspace_started ON run FIELDS workspace, started_at;
DEFINE TABLE OVERWRITE step SCHEMALESS;
DEFINE INDEX OVERWRITE step_run_idx ON step FIELDS run, idx UNIQUE;
DEFINE TABLE OVERWRITE experiment SCHEMALESS;
DEFINE INDEX OVERWRITE experiment_workspace ON experiment FIELDS workspace;
DEFINE TABLE OVERWRITE rca_report SCHEMALESS;
DEFINE TABLE OVERWRITE audit SCHEMALESS;
DEFINE TABLE OVERWRITE webhook SCHEMALESS;
DEFINE INDEX OVERWRITE webhook_workspace ON webhook FIELDS workspace;
DEFINE TABLE OVERWRITE benchmark SCHEMALESS;
DEFINE INDEX OVERWRITE benchmark_experiment ON benchmark FIELDS experiment;

-- graph edges (RELATE)
DEFINE TABLE OVERWRITE has_step TYPE RELATION IN run OUT step SCHEMALESS;
DEFINE TABLE OVERWRITE next TYPE RELATION IN step OUT step SCHEMALESS;
DEFINE TABLE OVERWRITE forked_from TYPE RELATION IN run OUT run SCHEMALESS;
DEFINE TABLE OVERWRITE tested TYPE RELATION IN experiment OUT run SCHEMALESS;
