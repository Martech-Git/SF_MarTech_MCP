"""OpenTelemetry setup. Spans carry tool names, steps and outcomes; never arguments or results."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from sf_mcp import SERVICE_NAME, __version__
from sf_mcp.config import Settings

tracer = trace.get_tracer("sf_mcp")


def configure_tracing(settings: Settings) -> None:
    if settings.otel_exporter != "gcp":
        return
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": SERVICE_NAME,
                "service.version": __version__,
                "deployment.environment": settings.environment,
            }
        )
    )
    exporter = CloudTraceSpanExporter(project_id=settings.gcp_project)  # type: ignore[no-untyped-call]
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None
