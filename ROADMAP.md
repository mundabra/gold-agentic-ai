# Roadmap

GOLD's next work is **proving and tightening its trust boundaries**, not adding agents, models or demo apps. This plan comes from an independent architecture and security review (September 2026), triaged by the maintainers. Every item is a GitHub issue; this page says what comes first and what waits.

## Principles we hold to

1. **A small core with optional modules.** Postgres before any new state system; OpenTelemetry rather than a custom observability API.
2. **Nothing heavy is mandatory.** No required service mesh, Redis, Kafka, Temporal, OPA or custom sandbox.
3. **Every production feature fails closed.** The demo stays a two-minute quickstart; production must be hard to start insecurely.
4. **Deterministic enforcement is the product.** Database permissions, RLS, signed approvals and retrieval filters are the guarantees. Guardrails and model quality are measured, never promised.
5. **Every security claim has a test.**

## Keep it simple: the rule for every change

Hardening must not turn GOLD into infrastructure soup. Each change has to pass this check before it merges:

- **No new mandatory component.** The demo still runs as today's containers, with no new required service, database, queue or sidecar. A new capability is optional, or it's switched on by the production profile.
- **Use the extension points that exist.** Add capabilities through the app manifest, the store interfaces, MCP tools and settings, not through a new framework or plugin system.
- **Standard parts over custom code:** PyJWT for tokens, Postgres for state, OpenTelemetry for telemetry, Kubernetes primitives for deployment.
- **Configuration over code, defaults that work.** A new setting needs a safe default and a line in the settings table; if it needs explaining in more than two sentences, the design is too complex.
- **Replace, don't pile up.** When a mechanism is superseded, delete the old one (after a one-release deprecation if users depend on it).
- **Smallest slice first.** Ship the simplest design that meets an issue's acceptance criteria; anything beyond that is a follow-up issue.

If an item can't meet this bar, it is re-scoped or goes to "Later", and the maintainer decides.

## Now: v0.6 "Trust boundaries" (P0)

In build order. The order puts what an adopting enterprise hits first (unsafe deployment settings, the security review) ahead of attacks that need an already-compromised internal service. The principal engineer re-checks this order before every run and may put something more urgent first (a red main branch, a real bug, a research finding), saying why on the issue.

| Order | Issue | What | Why this position |
|---:|---|---|---|
| ✅ | [#22](https://github.com/mundabra/gold-agentic-ai/issues/22) | CI gates: lint, dependency and secret scanning, image scan, Python 3.11, SBOM | Done (#41) |
| 1 | [#24](https://github.com/mundabra/gold-agentic-ai/issues/24) | Sanitize errors before they reach models and callers | Small; removes a leak class |
| 2 | [#20](https://github.com/mundabra/gold-agentic-ai/issues/20) | Production profile that fails closed, and `gold doctor` (first slice: today's settings) | The likeliest real failure is deploying demo settings; checks grow as #17 and #15 land |
| 3 | [#23](https://github.com/mundabra/gold-agentic-ai/issues/23) | Threat model, SECURITY.md, "when not to use GOLD" (first slice: honest current state) | The first thing an enterprise security review reads; updated with each fix |
| 4 | [#18](https://github.com/mundabra/gold-agentic-ai/issues/18) | App membership explicit by default | Small; closes the self-declared `app:` tag path |
| 5 | [#17](https://github.com/mundabra/gold-agentic-ai/issues/17) | Registry: authentication, SSRF defence, name binding | Control-plane entry point, reachable by any pod |
| 6 | [#15](https://github.com/mundabra/gold-agentic-ai/issues/15) | Separate signing keys for identity and approvals, with `iss`, `aud` and `kid` | Root of trust; #16 builds on it |
| 7 | [#16](https://github.com/mundabra/gold-agentic-ai/issues/16) | Approved actions resolved from platform config, not the ticket's URL | Needs audience-bound tokens from #15 |
| 8 | [#19](https://github.com/mundabra/gold-agentic-ai/issues/19) | Rejected approvals can't execute (state in Postgres) | Low exploitability today (same user); closes a documented limit |
| ∞ | [#21](https://github.com/mundabra/gold-agentic-ai/issues/21) | Adversarial test suite mapped to the README's guarantees | Grows with every fix above; closed when the guarantees table is fully linked |

**Done when** every "guaranteed" row in SECURITY.md links to a passing adversarial test.

## Next: v0.7 "Production posture" (P1)

Starts when v0.6 is released. Roughly in order:

- [#25](https://github.com/mundabra/gold-agentic-ai/issues/25) Asymmetric signing: agents and tools get verify-only keys
- [#26](https://github.com/mundabra/gold-agentic-ai/issues/26) Workload authentication for MCP and A2A calls (a mesh stays optional)
- [#27](https://github.com/mundabra/gold-agentic-ai/issues/27) Control-plane state in Postgres, so the orchestrator and registry run as replicas
- [#28](https://github.com/mundabra/gold-agentic-ai/issues/28) Helm production profile: PDB, HPA, resources, ServiceAccounts, external secrets, digests
- [#29](https://github.com/mundabra/gold-agentic-ai/issues/29) Versioned app manifest schema and `gold validate`
- [#30](https://github.com/mundabra/gold-agentic-ai/issues/30) Request budgets, timeouts, retries and circuit breakers
- [#31](https://github.com/mundabra/gold-agentic-ai/issues/31) Audit privacy (field redaction) and integrity (hash chain)
- [#32](https://github.com/mundabra/gold-agentic-ai/issues/32) OpenTelemetry metrics and a reference SLO dashboard
- [#33](https://github.com/mundabra/gold-agentic-ai/issues/33) Policy-driven approvals: risk tiers, a second approver, separation of duties
- [#34](https://github.com/mundabra/gold-agentic-ai/issues/34) RAG safety: retrieved text as data, injection tests, citation checks, provenance
- [#35](https://github.com/mundabra/gold-agentic-ai/issues/35) Governance eval suite; nightly real-model evals (**needs the owner**: an API key and a budget)
- [#36](https://github.com/mundabra/gold-agentic-ai/issues/36) Architecture decision records

## Optional provider profiles (separate track)

A provider profile makes GOLD quick to run on one specific cloud without touching the core. It maps GOLD's model roles (`gold-general`, `gold-sql`, `gold-embed`), database and Kubernetes settings to that provider's services, and it sits entirely in `deploy/providers/<provider>/` and `docs/providers/<provider>.md` (the AGENTS.md rule). The first profile is being built by a dedicated routine and tracked with its own label. This track never blocks the milestones above; its only core changes are a generic contract page and CI rendering of every profile.

## Later (worth doing, not now)

These wait until v0.7 lands, or until a user needs them:

- **GOLD Lite:** the same apps in a single process, for small deployments. High adoption value, but it needs a stable manifest schema (#29) first.
- Durable long-running actions (a job table in Postgres first; a workflow engine only if needed).
- Data classification and model egress rules; cost attribution and quotas per user, app and team.
- A semantic model for metrics, dimensions and joins; hybrid keyword and vector retrieval with re-ranking; PDF and Word ingestion.
- An NVIDIA NIM deployment profile; policy engine adapters (OPA, Cedar, OpenFGA); an agent catalog; a security-invariant status page.
- Slack and Microsoft Teams front-ends on the same identity and policy path.
- More databases, but only after a database-adapter security contract exists.

## Not planned

- **More agent frameworks** "for compatibility": the value is the platform contract.
- **More sample apps** unless one shows a genuinely new governance pattern.
- **Guardrails as the headline security mechanism:** they stay a best-effort layer.
- **Chasing benchmark numbers** before the evaluation sets are broader.
- **Mandatory infrastructure** (mesh, Redis, Kafka, Temporal, Vault, OPA).

## Where we read the review differently

- *"Add a first-party Helm chart":* GOLD has had one since v0.1. The real gap is a production profile (#20, #28).
- *"Fix naming drift":* done in v0.5.0 (repository, package, images and links are all `gold-agentic-ai`).
- *GOLD Lite as P1:* we agree it's valuable, but a single-process mode built before the manifest schema would have to be rebuilt, so it comes after #29.

## How the work gets done

- **A daily developer run** takes the next `ready` issue in the current milestone, in the order above. It writes a short plan on the issue, builds it with tests, opens a pull request and merges when CI is green, one issue per run.
- **A weekly architect run** checks health and dependencies, reviews the week's merged changes against this roadmap and the threat model, re-orders or splits issues, cuts a release when user-facing changes have landed, and posts a report to the **Weekly maintenance log** issue.
- **Issues labelled `needs-owner` wait for the maintainer:** credentials, budgets, positioning, renames, licensing, or anything that changes the default demo experience.
