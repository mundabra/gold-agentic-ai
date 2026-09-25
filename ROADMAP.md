# Roadmap

GOLD's next work is **proving and tightening its trust boundaries**, not adding agents, models or demo apps. This plan comes from an independent architecture and security review (September 2026), triaged by the maintainers. Every item is a GitHub issue; this page says what comes first and what waits.

## Principles we hold to

1. **A small core with optional modules.** Postgres before any new state system; OpenTelemetry rather than a custom observability API.
2. **Nothing heavy is mandatory.** No required service mesh, Redis, Kafka, Temporal, OPA or custom sandbox.
3. **Every production feature fails closed.** The demo stays a two-minute quickstart; production must be hard to start insecurely.
4. **Deterministic enforcement is the product.** Database permissions, RLS, signed approvals and retrieval filters are the guarantees. Guardrails and model quality are measured, never promised.
5. **Every security claim has a test.**

## Now: v0.6 "Trust boundaries" (P0)

In build order. Later items depend on earlier ones.

| Order | Issue | What | Why first |
|---:|---|---|---|
| 1 | [#22](https://github.com/mundabra/gold-agentic-ai/issues/22) | CI gates: lint, dependency and secret scanning, image scan, Python 3.11, SBOM | Protects every change after it |
| 2 | [#24](https://github.com/mundabra/gold-agentic-ai/issues/24) | Sanitize errors before they reach models and callers | Small; removes a leak class |
| 3 | [#18](https://github.com/mundabra/gold-agentic-ai/issues/18) | App membership explicit by default | Small; closes the self-declared `app:` tag path |
| 4 | [#17](https://github.com/mundabra/gold-agentic-ai/issues/17) | Registry: authentication, SSRF defence, name binding | Control-plane entry point |
| 5 | [#15](https://github.com/mundabra/gold-agentic-ai/issues/15) | Separate signing keys for identity and approvals, with `iss`, `aud` and `kid` | Root of trust; #16 builds on it |
| 6 | [#16](https://github.com/mundabra/gold-agentic-ai/issues/16) | Approved actions resolved from platform config, not the ticket's URL | Needs audience-bound tokens from #15 |
| 7 | [#19](https://github.com/mundabra/gold-agentic-ai/issues/19) | Rejected approvals can't execute (state in Postgres) | Closes a documented limit |
| 8 | [#20](https://github.com/mundabra/gold-agentic-ai/issues/20) | Production profile that fails closed, and `gold doctor` | Checks the controls above |
| 9 | [#21](https://github.com/mundabra/gold-agentic-ai/issues/21) | Adversarial test suite mapped to the README's guarantees | Grows with each fix; finished last |
| 10 | [#23](https://github.com/mundabra/gold-agentic-ai/issues/23) | Threat model, SECURITY.md, "when not to use GOLD" | Written last, so it describes what is true |

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
