from gold import telemetry


def test_tracing_is_off_without_an_otlp_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    app = object()
    assert telemetry.setup("test") is False
    assert telemetry.wrap(app, "test") is app


def test_trace_content_is_hidden_by_default():
    from gold import config

    assert config.TRACE_CONTENT is False
