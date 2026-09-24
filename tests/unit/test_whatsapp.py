import asyncio
import json

from twilio.http.response import Response
import pytest

from app.core.config import Settings
from app.domain import EnvioError, EnvioIncertoError, StatusEnvio, normalizar_destinatario
from app.integrations.whatsapp_client import WhatsAppClient


@pytest.mark.parametrize("telefone,esperado", [
    ("(86) 99999-9999", "5586999999999"),
    ("86 99999-9999", "5586999999999"),
    ("+55 86 99999-9999", "5586999999999"),
    ("whatsapp:+55 86 99999-9999", "5586999999999"),
    ("5586999999999", "5586999999999"),
    ("(11) 3333-4444", "551133334444"),
    ("(86) 9442-3074", "558694423074"),
    ("+55 86 9442-3074", "558694423074"),
    ("+1 (555) 000-0001", "15550000001"),
])
def test_normalizacao_telefone_e_idempotencia(telefone, esperado):
    assert normalizar_destinatario(telefone) == esperado
    assert normalizar_destinatario(esperado) == esperado


@pytest.mark.parametrize("telefone", [
    "", " ", "99999-9999", "abc86999999999", "++5586999999999",
    "55+86999999999", "(00) 99999-9999", "(86) 88888-8888",
    "+55 86 999-9999", "5586999999999999", "(86) 99999-9999 ramal 1",
])
def test_telefone_invalido(telefone):
    with pytest.raises(ValueError):
        normalizar_destinatario(telefone)


def gateway():
    return WhatsAppClient("AC" + "0" * 32, "ficticio", "whatsapp:+15550000002")


@pytest.mark.parametrize("provider_status,status", [
    ("queued", StatusEnvio.ACEITO), ("sent", StatusEnvio.ACEITO),
    ("failed", StatusEnvio.ERRO), ("undelivered", StatusEnvio.ERRO),
    ("canceled", StatusEnvio.ERRO), ("novo_estado", StatusEnvio.INCERTO),
])
@pytest.mark.parametrize("prefixo", ["SM", "MM"])
def test_status_retornado_pelo_sdk(provider_status, status, prefixo, twilio_request):
    twilio_request.side_effect = None
    twilio_request.return_value = Response(201, json.dumps({
        "sid": prefixo + "1" * 32, "status": provider_status, "to": "whatsapp:+5586999999999",
        "error_message": "detalhe privado", "error_code": None,
    }))
    resultado = asyncio.run(gateway().enviar("5586999999999", "Panorama de teste"))
    assert resultado.provedor_id == prefixo + "1" * 32
    assert resultado.provedor_status == provider_status
    assert resultado.status == status
    assert "privado" not in (resultado.erro or "")
    assert twilio_request.await_count == 1


@pytest.mark.parametrize("payload", [
    {}, {"sid": "invalido", "status": "queued", "to": "whatsapp:+5586999999999"},
    {"sid": "SM" + "1" * 32, "status": "queued", "to": "whatsapp:+15550000003"},
])
def test_resposta_invalida_ou_destino_divergente(payload, twilio_request):
    twilio_request.side_effect = None
    twilio_request.return_value = Response(201, json.dumps(payload))
    with pytest.raises(EnvioIncertoError):
        asyncio.run(gateway().enviar("5586999999999", "Teste"))
    assert twilio_request.await_count == 1


@pytest.mark.parametrize("codigo,esperado", [
    (20003, "Credenciais"), (63002, "Remetente"), (63007, "Remetente"),
    (63015, "Sandbox"), (63016, "Janela"), (29999, "Console"),
])
def test_rejeicao_twilio_informa_codigo_sem_payload_privado(codigo, esperado, twilio_request):
    twilio_request.side_effect = None
    twilio_request.return_value = Response(400, json.dumps({
        "code": codigo, "message": "detalhe privado", "status": 400,
    }))
    with pytest.raises(EnvioError) as erro:
        asyncio.run(gateway().enviar("5586999999999", "Teste"))
    assert esperado in str(erro.value)
    assert f"código Twilio {codigo}" in str(erro.value)
    assert "privado" not in str(erro.value)
    assert twilio_request.await_count == 1


@pytest.mark.parametrize("mensagem", ["", " ", "x" * 1601])
def test_mensagem_invalida_nao_chama_twilio(mensagem, twilio_request):
    with pytest.raises(EnvioError):
        asyncio.run(gateway().enviar("5586999999999", mensagem))
    twilio_request.assert_not_awaited()


@pytest.mark.parametrize("falha", [False, True])
def test_sessao_sdk_fecha_em_sucesso_e_falha(monkeypatch, twilio_request, falha):
    from app.integrations import whatsapp_client
    real_client = whatsapp_client.Client
    transportes = []

    def criar_client(*args, **kwargs):
        transportes.append(kwargs["http_client"])
        return real_client(*args, **kwargs)

    monkeypatch.setattr(whatsapp_client, "Client", criar_client)
    if falha:
        twilio_request.side_effect = TimeoutError("simulado")
        with pytest.raises(EnvioIncertoError):
            asyncio.run(gateway().enviar("5586999999999", "Teste"))
    else:
        asyncio.run(gateway().enviar("5586999999999", "Teste"))
    assert transportes[0].session.closed


@pytest.mark.parametrize("campos", [
    {"twilio_auth_token": "ficticio"},
    {"twilio_account_sid": "invalido", "twilio_auth_token": "ficticio", "twilio_whatsapp_from": "whatsapp:+15550000002"},
    {"twilio_account_sid": "AC" + "0" * 32, "twilio_auth_token": "ficticio", "twilio_whatsapp_from": "15550000002"},
])
def test_configuracao_incompleta_ou_invalida(campos):
    with pytest.raises(ValueError):
        Settings(**campos)


def test_destinatario_padrao_do_env_e_normalizado(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda *_: None)
    monkeypatch.setenv("TWILIO_WHATSAPP_TO", "whatsapp:+55 86 99999-9999")
    assert Settings.from_env().twilio_whatsapp_to == "5586999999999"
