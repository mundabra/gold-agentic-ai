"""Distributed tracing with OpenTelemetry: one question becomes one trace across
the orchestrator, the A2A agents, the MCP tool servers, the database and the model calls.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT (or OTEL_EXPORTER_OTLP_TRACES_ENDPOINT) is set,
so any OTLP backend works: Jaeger, Grafana Tempo, an OpenTelemetry Collector, or a
commercial APM. Needs the extra: pip install "gold-ai-agent[otel]".

Prompts, SQL and results are kept out of spans unless GOLD_TRACE_CONTENT=true, because
tracing backends are often readable by more people than the data itself.
"""

import logging
import os

from gold import config

log = logging.getLogger("gold.telemetry")
_enabled = False


def enabled() -> bool:
    return _enabled


def setup(component: str) -> bool:
    """Start tracing for this process if an OTLP endpoint is configured. Safe to call more than once."""
    global _enabled
    if _enabled:
        return True
    if not (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")):
        return False
    try:
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning('OTEL_EXPORTER_OTLP_ENDPOINT is set but tracing is not installed: pip install "gold-ai-agent[otel]"')
        return False

    if not config.TRACE_CONTENT:
        for name in ("OPENINFERENCE_HIDE_INPUTS", "OPENINFERENCE_HIDE_OUTPUTS"):
            os.environ.setdefault(name, "true")

    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", f"gold-{component}"),
        "service.namespace": "gold",
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # Outgoing HTTP (A2A calls, MCP calls, model calls) carries the W3C traceparent header,
    # so spans from every service join the same trace.
    HTTPXClientInstrumentor().instrument()
    PsycopgInstrumentor().instrument(enable_commenter=False)
    # Agent runs, tool calls and model calls as spans. exclusive_processor replaces the
    # SDK's default exporter, so nothing is sent to OpenAI's trace service.
    OpenAIAgentsInstrumentor().instrument(tracer_provider=provider, exclusive_processor=True)
    from agents import set_tracing_disabled

    set_tracing_disabled(False)
    _enabled = True
    log.info("tracing on: exporting OTLP spans as %s", resource.attributes["service.name"])
    return True


def wrap(app, component: str):
    """Start tracing and wrap an ASGI app so incoming requests continue the caller's trace."""
    if not setup(component):
        return app
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

    return OpenTelemetryMiddleware(app)
