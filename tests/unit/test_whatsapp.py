import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.domain import EnvioError, normalizar_destinatario
from app.integrations.whatsapp_client import WhatsAppClient


@pytest.mark.parametrize("telefone,esperado", [
    ("(86) 99999-9999", "5586999999999"),
    ("86 99999-9999", "5586999999999"),
    ("+55 86 99999-9999", "5586999999999"),
    ("5586999999999", "5586999999999"),
    ("(11) 3333-4444", "551133334444"),
    ("+1 (555) 000-0001", "15550000001"),
])
def test_normalizacao_telefone_e_idempotencia(telefone, esperado):
    assert normalizar_destinatario(telefone) == esperado
    assert normalizar_destinatario(esperado) == esperado


@pytest.mark.parametrize("telefone", [
    "", " ", "99999-9999", "abc86999999999", "++5586999999999",
    "55+86999999999", "(00) 99999-9999", "(86) 88888-8888",
    "+55 86 9999-9999", "5586999999999999", "(86) 99999-9999 ramal 1",
])
def test_telefone_invalido(telefone):
    with pytest.raises(ValueError):
        normalizar_destinatario(telefone)


def test_template_com_mensagem_dinamica_sem_fallback_para_texto():
    async def executar():
        def handler(request):
            payload = json.loads(request.content)
            assert payload["to"] == "5586999999999"
            assert payload["type"] == "template"
            assert "text" not in payload
            assert payload["template"] == {
                "name": "panorama_teste", "language": {"code": "pt_BR"},
                "components": [{"type": "body", "parameters": [{
                    "type": "text", "text": "Panorama Cotas ativas: 1.234 Crédito médio: R$ 50.000,00",
                }]}],
            }
            return httpx.Response(200, json={"messages": [{"id": "wamid.teste"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = WhatsAppClient(client, "ficticio", "123", "v23.0", template_name="panorama_teste")
            assert await gateway.enviar("5586999999999", "Panorama\n\nCotas ativas: 1.234\nCrédito médio: R$ 50.000,00") == "wamid.teste"
    asyncio.run(executar())


def test_template_longo_falha_sem_chamar_meta():
    async def executar():
        def handler(request):
            pytest.fail("A mensagem inválida não deve ser enviada")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = WhatsAppClient(client, "ficticio", "123", "v23.0", template_name="panorama_teste")
            with pytest.raises(EnvioError, match="não cabe"):
                await gateway.enviar("5586999999999", "x" * 1025)
    asyncio.run(executar())


def test_template_rejeitado_nao_dispara_texto_como_fallback():
    async def executar():
        chamadas = []

        def handler(request):
            chamadas.append(json.loads(request.content))
            return httpx.Response(400, json={"error": {"message": "detalhe privado do template"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = WhatsAppClient(client, "ficticio", "123", "v23.0", template_name="panorama_teste")
            with pytest.raises(EnvioError) as erro:
                await gateway.enviar("5586999999999", "Mensagem dinâmica de teste")
            assert "privado" not in str(erro.value)
            assert len(chamadas) == 1
            assert chamadas[0]["type"] == "template"
    asyncio.run(executar())


@pytest.mark.parametrize("campos", [
    {"whatsapp_token": "ficticio"},
    {"whatsapp_template_name": "panorama"},
    {"whatsapp_token": "ficticio", "whatsapp_phone_number_id": "123", "whatsapp_api_version": "v23.0",
     "whatsapp_template_name": "nome inválido"},
    {"whatsapp_token": "ficticio", "whatsapp_phone_number_id": "123", "whatsapp_api_version": "v23.0",
     "whatsapp_template_name": "panorama", "whatsapp_template_language": ""},
])
def test_configuracao_incompleta_ou_invalida(campos):
    with pytest.raises(ValueError):
        Settings(**campos)
