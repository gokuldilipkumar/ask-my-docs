from observability.tracer import NoOpTracer


def test_noop_tracer_span_is_a_context_manager_yielding_a_handle():
    tracer = NoOpTracer()

    with tracer.span("retrieval.bm25.search") as handle:
        handle.update(usage_details={"input": 10, "output": 5}, cost_details={"total": 0.01})

    # no exception anywhere above is the assertion -- NoOpTracer must accept any span name,
    # any as_type, and any update() kwargs without requiring Langfuse or raising


def test_noop_tracer_span_accepts_as_type_and_model_kwargs():
    tracer = NoOpTracer()

    with tracer.span("generate.answer", as_type="generation", model="claude-sonnet-5") as handle:
        handle.update(output="ok")
