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


def gateway(content_sid: str = "HX" + "1" * 32, is_production: bool = False):
    return WhatsAppClient("AC" + "0" * 32, "ficticio", "whatsapp:+15550000002",
                          content_sid=content_sid, is_production=is_production)


@pytest.mark.parametrize("provider_status,status", [
    ("queued", StatusEnvio.NA_FILA), ("sent", StatusEnvio.ENVIADO),
    ("delivered", StatusEnvio.ENTREGUE), ("read", StatusEnvio.LIDO),
    ("failed", StatusEnvio.FALHOU), ("undelivered", StatusEnvio.NAO_ENTREGUE),
    ("canceled", StatusEnvio.FALHOU), ("novo_estado", StatusEnvio.INCERTO),
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
    (20003, "Credenciais"), (21654, "Try out WhatsApp"),
    (63002, "Remetente"), (63007, "Remetente"),
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


def test_envio_preserva_texto_da_consulta_em_producao(twilio_request):
    mensagem = "Panorama do mercado — Automóveis\nCotas ativas: 5.558.340\nCrédito médio: R$ 75.950,00"
    resultado = asyncio.run(gateway(is_production=True).enviar("5586999999999", mensagem))
    assert resultado.status == StatusEnvio.NA_FILA
    assert resultado.mensagem_enviada == mensagem
    payload = twilio_request.call_args.kwargs["data"]
    assert payload["Body"] == mensagem
    assert "ContentSid" not in payload


def test_envio_modo_demo_utiliza_content_sid_sem_body(twilio_request):
    mensagem = "Panorama do mercado — Automóveis\nCotas ativas: 5.558.340"
    client = WhatsAppClient("AC" + "0" * 32, "ficticio", "whatsapp:+15550000002",
                            content_sid="HX" + "2" * 32, is_production=False)
    resultado = asyncio.run(client.enviar("5586999999999", mensagem))
    assert resultado.status == StatusEnvio.NA_FILA
    payload = twilio_request.call_args.kwargs["data"]
    assert payload["ContentSid"] == "HX" + "2" * 32
    assert "Body" not in payload
    assert "HX" + "2" * 32 in (resultado.mensagem_enviada or "")


def test_envio_modo_demo_sem_content_sid_gera_erro_controlado(twilio_request):
    client = WhatsAppClient("AC" + "0" * 32, "ficticio", "whatsapp:+15550000002",
                            content_sid="", is_production=False)
    with pytest.raises(EnvioError) as exc:
        asyncio.run(client.enviar("5586999999999", "Mensagem de teste"))
    assert "Envio WhatsApp indisponível no ambiente de demonstração" in str(exc.value)
    assert "TWILIO_CONTENT_SID" in str(exc.value)
    twilio_request.assert_not_awaited()


def test_envio_modo_demo_com_content_variables(twilio_request):
    vars_json = json.dumps({"1": "Automóveis", "2": "5.558.340"})
    client = WhatsAppClient("AC" + "0" * 32, "ficticio", "whatsapp:+15550000002",
                            content_sid="HX" + "3" * 32, content_variables=vars_json, is_production=False)
    resultado = asyncio.run(client.enviar("5586999999999", "Mensagem"))
    assert resultado.status == StatusEnvio.NA_FILA
    payload = twilio_request.call_args.kwargs["data"]
    assert payload["ContentSid"] == "HX" + "3" * 32
    assert payload["ContentVariables"] == vars_json
    assert "Body" not in payload


def test_template_rejeita_mensagem_antiga_ou_arbitraria(twilio_request):
    client = WhatsAppClient("AC" + "0" * 32, "ficticio", "whatsapp:+15550000002",
                            panorama_content_sid="HX" + "a" * 32)
    with pytest.raises(EnvioError, match="nova consulta"):
        asyncio.run(client.enviar("5586999999999", "Panorama antigo"))
    twilio_request.assert_not_awaited()


@pytest.mark.parametrize("sid", ["invalido", "HX" + "a" * 32])
def test_template_exige_sid_valido_e_credenciais(sid):
    with pytest.raises(ValueError):
        Settings(twilio_panorama_content_sid=sid)


def test_carrega_sid_do_template_de_panorama(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda *_: None)
    monkeypatch.delenv("TWILIO_CONTENT_SID", raising=False)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "ficticio")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+15550000002")
    monkeypatch.setenv("TWILIO_PANORAMA_CONTENT_SID", "HX" + "a" * 32)
    assert Settings.from_env().twilio_panorama_content_sid == "HX" + "a" * 32
