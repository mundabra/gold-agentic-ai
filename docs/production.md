# Production checklist

GOLD is a reference architecture: the controls below are built in and tested, and the list after them is what your environment adds.

## Built in

| Area | What GOLD does |
|---|---|
| Read-only | Guardrail before any model call; SQLGlot parsing that allows one `SELECT`; single-statement execution; a database login with SELECT rights and read-only transactions. |
| Personal data | Column-level grants: the login cannot read personal-data columns at all. Emails and phone numbers are scrubbed from returned text and error messages. |
| Cost and load | Dry-run cost limit (`GOLD_MAX_QUERY_COST`), 10-second statement timeout, row cap, SQL token budget. |
| Containers | Non-root user, read-only root filesystem, all capabilities dropped, health checks on every service. |
| Secrets | Each Kubernetes Deployment receives only the secrets it uses. `llm.existingSecret` and `database.existingSecret` keep keys out of Helm values. |
| Network | Optional NetworkPolicies (`networkPolicy.enabled`) allow only the connections GOLD needs. Compose publishes ports on 127.0.0.1 only. |
| Safety rails | Optional NVIDIA NeMo Guardrails on every question and answer, failing closed ([guardrails](guardrails.md)). |
| Registry | Optional shared token (`GOLD_REGISTRY_TOKEN`) for registration. A live agent's name can't be taken over by another service. |
| Memory | Conversation history in a SQLite file, or a shared database (`GOLD_SESSION_DB_URL`) for more than one orchestrator replica. |
| Tracing | OpenTelemetry traces across every service, one trace per question; prompts and results kept out of spans by default ([observability](observability.md)). |
| Audit | One JSON record per question (answered or blocked): question, agents, exact SQL, rows, tokens, time, trace ID. |
| Quality | `gold eval` as a CI gate; `gold bench` and `scripts/aiperf.sh` for latency and cost. |

## You add

- [ ] **Sign-in** in front of the orchestrator: your OIDC provider through an ingress or an authenticating proxy. GOLD has no user accounts of its own.
- [ ] **Registry token** (`registry.token`), and NetworkPolicies or a service mesh with mTLS between services. The MCP tool servers have no authentication of their own.
- [ ] **Column grants for your data:** grant GOLD's login only the columns it may read, in the same way as `deploy/postgres/03-reader-role.sh`.
- [ ] **Audit storage:** ship the `gold.audit` JSON lines from stdout (or `GOLD_AUDIT_LOG`) to your log or audit store, with retention and access rules.
- [ ] **Secrets manager** for model keys and database credentials.
- [ ] **Shared conversation memory** (`pip install "gold-ai-agent[sessions]"` and `GOLD_SESSION_DB_URL`) before running more than one orchestrator replica.
- [ ] **Model gateway policies:** budgets, rate limits and fallbacks in LiteLLM.
- [ ] **Tracing backend:** point `OTEL_EXPORTER_OTLP_ENDPOINT` at your OpenTelemetry Collector or APM, and restrict who can read traces.
- [ ] **Pinned images:** pin the LiteLLM and vLLM image tags you have tested.
- [ ] **Data egress review:** with a hosted model (stage 1), the schema, questions, definitions and query results are sent to that provider.

## Known limits

- **Names are readable by design.** Customer and employee names are needed for questions like "top customers". Remove those grants if your policy requires it.
- **The built-in input guardrail is a keyword filter, and model-based rails are best effort.** They stop obvious misuse early and cheaply. The guarantee comes from the database permissions, not from any filter or rail.
- **The answer text is written by the orchestrator model.** It quotes the SQL and definitions, but the authoritative record is the audit trail and the trace, which hold the exact query that ran.
- **Free-text scrubbing is pattern-based.** It catches emails and international phone formats. Keep personal data out through column grants, not scrubbing.
- **The registry keeps state in memory.** Agents re-register every 30 seconds, so it recovers from restarts. Run one replica.
