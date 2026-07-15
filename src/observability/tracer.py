from contextlib import contextmanager
from typing import Any, ContextManager, Protocol


class SpanHandle(Protocol):
    def update(self, **kwargs: Any) -> None: ...


class Tracer(Protocol):
    def span(
        self, name: str, *, as_type: str = "span", model: str | None = None
    ) -> ContextManager[SpanHandle]: ...


class _NoOpSpanHandle:
    def update(self, **kwargs: Any) -> None:
        pass


class NoOpTracer:
    @contextmanager
    def span(self, name: str, *, as_type: str = "span", model: str | None = None):
        yield _NoOpSpanHandle()
