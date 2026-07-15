from config.settings import Settings
from observability.langfuse_tracer import LangfuseTracer, get_tracer
from observability.tracer import NoOpTracer


class FakeLangfuseClient:
    def __init__(self):
        self.observation_calls = []

    def start_as_current_observation(self, *, name, as_type="span", model=None):
        self.observation_calls.append({"name": name, "as_type": as_type, "model": model})

        class FakeSpan:
            def __init__(self):
                self.update_calls = []

            def update(self, **kwargs):
                self.update_calls.append(kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakeSpan()


def test_langfuse_tracer_opens_a_named_observation_and_yields_an_updatable_handle():
    client = FakeLangfuseClient()
    tracer = LangfuseTracer(client)

    with tracer.span("generate.answer", as_type="generation", model="claude-sonnet-5") as handle:
        handle.update(usage_details={"input": 10, "output": 5})

    assert client.observation_calls == [
        {"name": "generate.answer", "as_type": "generation", "model": "claude-sonnet-5"}
    ]


def test_get_tracer_returns_noop_when_langfuse_disabled():
    settings = Settings(anthropic_api_key="x")
    settings.observability.langfuse_enabled = False
    settings.langfuse_public_key = "pk"
    settings.langfuse_secret_key = "sk"

    assert isinstance(get_tracer(settings), NoOpTracer)


def test_get_tracer_returns_noop_when_credentials_missing():
    settings = Settings(anthropic_api_key="x")
    settings.observability.langfuse_enabled = True
    settings.langfuse_public_key = None
    settings.langfuse_secret_key = None

    assert isinstance(get_tracer(settings), NoOpTracer)


def test_get_tracer_returns_langfuse_tracer_when_enabled_and_configured():
    settings = Settings(anthropic_api_key="x")
    settings.observability.langfuse_enabled = True
    settings.langfuse_public_key = "pk-fake"
    settings.langfuse_secret_key = "sk-fake"

    tracer = get_tracer(settings)

    assert isinstance(tracer, LangfuseTracer)
    # Constructing a real Langfuse client with fake keys never raises (probe-verified,
    # see plan's Conventions Check) -- no live_langfuse gate needed for this assertion alone.
