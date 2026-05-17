from rufino.engine.process.llm_client import (
    LLMClient,
    StubLLMClient,
    LLMResponse,
)


def test_stub_returns_canned_response():
    stub = StubLLMClient(canned_response="---\ntitle: stub\n---\nBody from stub.\n")
    resp = stub.complete(prompt="ignored", model="sonnet")
    assert isinstance(resp, LLMResponse)
    assert "stub" in resp.text


def test_stub_protocol_compliance():
    stub = StubLLMClient(canned_response="x")
    assert isinstance(stub, LLMClient)


def test_stub_records_calls():
    stub = StubLLMClient(canned_response="r")
    stub.complete(prompt="hello", model="sonnet")
    stub.complete(prompt="world", model="opus")
    assert len(stub.calls) == 2
    assert stub.calls[0] == ("hello", "sonnet")
