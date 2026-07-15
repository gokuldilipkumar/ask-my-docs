from contextlib import contextmanager

from langfuse import Langfuse

from config.settings import Settings
from observability.tracer import NoOpTracer, Tracer


class LangfuseTracer:
    def __init__(self, client: Langfuse):
        self._client = client

    @contextmanager
    def span(self, name: str, *, as_type: str = "span", model: str | None = None):
        with self._client.start_as_current_observation(name=name, as_type=as_type, model=model) as span:
            yield span


def get_tracer(settings: Settings) -> Tracer:
    if not settings.observability.langfuse_enabled:
        return NoOpTracer()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return NoOpTracer()
    client = Langfuse(public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key)
    return LangfuseTracer(client)
