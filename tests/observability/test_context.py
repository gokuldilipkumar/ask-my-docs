from config.settings import ObservabilityConfig
from observability.context import ObservabilityContext, noop_observability
from observability.tracer import NoOpTracer


def test_noop_observability_bundles_a_noop_tracer_and_default_config():
    context = noop_observability()

    assert isinstance(context, ObservabilityContext)
    assert isinstance(context.tracer, NoOpTracer)
    assert isinstance(context.config, ObservabilityConfig)


def test_observability_context_holds_whatever_tracer_and_config_are_given():
    tracer = NoOpTracer()
    config = ObservabilityConfig(daily_cost_cap_usd=1.0)

    context = ObservabilityContext(tracer=tracer, config=config)

    assert context.tracer is tracer
    assert context.config is config
