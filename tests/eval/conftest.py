from types import SimpleNamespace

import pytest


class FakeStructuredClient:
    """Fakes `client.with_options(...).messages.parse(...)` for eval judge tests."""

    def __init__(self, parsed_output=None, truncate=False):
        self.with_options_kwargs = None
        self.parse_kwargs = None
        self._parsed_output = parsed_output
        self._truncate = truncate

    def with_options(self, **kwargs):
        self.with_options_kwargs = kwargs
        return self

    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        self.parse_kwargs = kwargs
        if self._truncate:
            kwargs["output_format"].model_validate_json('{"truncated')  # raises ValidationError
        parsed_output = self._parsed_output

        class FakeResponse:
            pass

        FakeResponse.parsed_output = parsed_output
        FakeResponse.usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        return FakeResponse()


@pytest.fixture
def make_fake_structured_client():
    return FakeStructuredClient
