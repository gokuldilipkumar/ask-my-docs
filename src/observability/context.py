from dataclasses import dataclass

from config.settings import ObservabilityConfig
from observability.tracer import NoOpTracer, Tracer


@dataclass
class ObservabilityContext:
    tracer: Tracer
    config: ObservabilityConfig


def noop_observability() -> ObservabilityContext:
    return ObservabilityContext(tracer=NoOpTracer(), config=ObservabilityConfig())
