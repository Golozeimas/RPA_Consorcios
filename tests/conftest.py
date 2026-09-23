"""A fronteira do SDK Twilio é sempre simulada: nenhum teste envia mensagens reais."""

import json
from unittest.mock import AsyncMock

import pytest
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.http.response import Response


@pytest.fixture(autouse=True)
def twilio_request(monkeypatch):
    async def responder(*args, **kwargs):
        return Response(201, json.dumps({
            "sid": "SM" + "1" * 32, "status": "queued",
            "to": kwargs["data"]["To"], "error_code": None,
        }))

    request = AsyncMock(side_effect=responder)
    monkeypatch.setattr(AsyncTwilioHttpClient, "request", request)
    return request
