import pytest

from govhub_shared.model_gateway import DraftRequest, ModelGateway, NullGateway


def test_null_gateway_satisfies_protocol_and_refuses() -> None:
    gw = NullGateway()
    assert isinstance(gw, ModelGateway)
    with pytest.raises(NotImplementedError):
        gw.draft(DraftRequest(task="t", prompt="p"))
