"""Fronteiras HTTP simuladas; nunca envia mensagens reais."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os

from aiohttp import ClientConnectionError
from twilio.http.response import Response as TwilioResponse
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.domain import PersistenciaError
from app.main import create_app
from app.repositories.envio_repository import SQLiteEnvioRepository


# Recorte real da resposta BCB de junho/2026 para os segmentos do teste.
BCB_PAYLOAD = {"value": [
    {"DataBase": 202606, "IdMetrica": "13", "Grupo": "Cotas ativas", "Metrica": "Cotas ativas - Automóveis", "Valor": 5558.34, "Unidade": "mil"},
    {"DataBase": 202606, "IdMetrica": "88", "Grupo": "Valor Médio", "Metrica": "Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Automóveis", "Valor": 75.95, "Unidade": "R$ mil"},
    {"DataBase": 202606, "IdMetrica": "95", "Grupo": "Prazo Médio", "Metrica": "Prazo médio dos grupos constituídos nos últimos 12 meses - Automóveis", "Valor": 90.0, "Unidade": "meses"},
    {"DataBase": 202606, "IdMetrica": "81", "Grupo": "Taxa de Administração", "Metrica": "Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Automóveis", "Valor": 15.16, "Unidade": "%"},
    {"DataBase": 202606, "IdMetrica": "34", "Grupo": "Ativos Contemplados", "Metrica": "Cotas ativas contempladas nos últimos 12 meses - Automóveis", "Valor": 818.74, "Unidade": "mil"},
    {"DataBase": 202606, "IdMetrica": "11", "Grupo": "Cotas ativas", "Metrica": "Cotas ativas - Imóveis", "Valor": 3202.55, "Unidade": "mil"},
    {"DataBase": 202606, "IdMetrica": "17", "Grupo": "Cotas ativas", "Metrica": "Cotas ativas - Ônibus e Micro-ônibus (cód. 21)", "Valor": 10.68, "Unidade": "mil"},
]}
ENTRADA = {"segmento": "Automóveis", "periodo": "2026-06"}
DESTINO = {"destinatario": "+1 (555) 000-0001"}


@pytest.mark.parametrize("sem_opcionais", [False, True])
def test_template_automoveis_mapeia_consulta_e_preserva_historico(tmp_path, twilio_request, sem_opcionais):
    config = replace(settings(tmp_path), twilio_panorama_content_sid="HX" + "a" * 32)
    payload = {"value": [BCB_PAYLOAD["value"][0]]} if sem_opcionais else BCB_PAYLOAD
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        assert envio["status"] == "NA_FILA"
        requisicao = twilio_request.call_args.kwargs["data"]
        assert requisicao["ContentSid"] == config.twilio_panorama_content_sid
        assert "Body" not in requisicao
        variaveis = json.loads(requisicao["ContentVariables"])
        assert variaveis == {
            "1": "2026-06 (2º trimestre)", "2": "5.558.340",
            "3": "Não disponível" if sem_opcionais else "R$ 75.950,00",
            "4": "Não disponível" if sem_opcionais else "90 meses",
            "5": "Não disponível" if sem_opcionais else "15,16%",
            "6": "Não disponível" if sem_opcionais else "818.740",
        }
        assert envio["mensagem"] == consulta["mensagem_gerada"]
        for valor in variaveis.values():
            assert valor in envio["mensagem"]
        assert client.get(rota).json() == [envio]
        assert client.post(rota, json=DESTINO).json() == envio
        assert twilio_request.await_count == 1


def test_template_automoveis_bloqueia_outro_segmento(tmp_path, twilio_request):
    config = replace(settings(tmp_path), twilio_panorama_content_sid="HX" + "a" * 32)
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json={**ENTRADA, "segmento": "Imóveis"}).json()
        envio = client.post(f"/api/consultas/{consulta['id']}/envios", json=DESTINO).json()
        assert envio["status"] == "ERRO"
        assert "Automóveis" in envio["erro"]
        twilio_request.assert_not_awaited()


def settings(tmp_path):
    return Settings(database_path=tmp_path / "http.sqlite3", twilio_auth_token="token-ficticio-de-teste",
                    twilio_account_sid="AC" + "0" * 32, twilio_whatsapp_from="whatsapp:+15550000002",
                    twilio_production_sender=True)


def test_twilio_envia_mensagem_da_consulta_e_bloqueia_duplicidade(tmp_path, twilio_request):
    config = settings(tmp_path)
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        assert consulta["status"] == "SUCESSO"
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json={"destinatario": "+55 86 9442-3074"}).json()
        assert envio["status"] == "NA_FILA"
        assert envio["provedor_id"] == "SM" + "1" * 32
        assert envio["provedor_status"] == "queued"
        assert envio["provider"] == "twilio"
        assert envio["initial_status"] == "queued"
        assert envio["mensagem"] == consulta["mensagem_gerada"]
        # Segundo disparo é bloqueado pela proteção de idempotência
        assert client.post(rota, json=DESTINO).json() == envio
        assert client.get(rota).json() == [envio]
        assert twilio_request.await_count == 1


def test_twilio_status_callback_fluxo_completo_e_ordem_de_eventos(tmp_path, twilio_request):
    config = replace(settings(tmp_path), twilio_validate_signature=False)
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        sid = envio["provedor_id"]
        assert envio["status"] == "NA_FILA"

        # 1. Evento: sent -> ENVIADO
        resp = client.post("/webhooks/twilio/message-status", data={
            "MessageSid": sid, "MessageStatus": "sent", "AccountSid": config.twilio_account_sid,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert resp.status_code == 204
        atualizado = client.get(rota).json()[0]
        assert atualizado["status"] == "ENVIADO"
        assert atualizado["sent_at"] is not None

        # 2. Evento: delivered -> ENTREGUE
        resp = client.post("/webhooks/twilio/message-status", data={
            "MessageSid": sid, "MessageStatus": "delivered", "AccountSid": config.twilio_account_sid,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert resp.status_code == 204
        atualizado = client.get(rota).json()[0]
        assert atualizado["status"] == "ENTREGUE"
        assert atualizado["delivered_at"] is not None

        # 3. Evento: read -> LIDO
        resp = client.post("/webhooks/twilio/message-status", data={
            "MessageSid": sid, "EventType": "read", "AccountSid": config.twilio_account_sid,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert resp.status_code == 204
        atualizado = client.get(rota).json()[0]
        assert atualizado["status"] == "LIDO"
        assert atualizado["read_at"] is not None

        # 4. Evento fora de ordem atrasado (sent após read) não deve regredir
        resp = client.post("/webhooks/twilio/message-status", data={
            "MessageSid": sid, "MessageStatus": "sent", "AccountSid": config.twilio_account_sid,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert resp.status_code == 204
        assert client.get(rota).json()[0]["status"] == "LIDO"


def test_twilio_status_callback_failed_undelivered_e_validacoes(tmp_path, twilio_request):
    config = replace(settings(tmp_path), twilio_validate_signature=False)
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        sid = envio["provedor_id"]

        # Callback com falha e ErrorCode
        resp = client.post("/webhooks/twilio/message-status", data={
            "MessageSid": sid, "MessageStatus": "failed", "ErrorCode": "63015",
            "AccountSid": config.twilio_account_sid,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert resp.status_code == 204
        atualizado = client.get(rota).json()[0]
        assert atualizado["status"] == "FALHOU"
        assert atualizado["error_code"] == 63015
        assert "Sandbox" in atualizado["erro"]

        # Content-type incorreto
        assert client.post("/webhooks/twilio/message-status", json={"MessageSid": sid}).status_code == 415

        # MessageSid inexistente
        assert client.post("/webhooks/twilio/message-status", data={
            "MessageSid": "SM" + "9" * 32, "MessageStatus": "delivered",
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 404

        # AccountSid divergente
        assert client.post("/webhooks/twilio/message-status", data={
            "MessageSid": sid, "MessageStatus": "delivered", "AccountSid": "AC" + "9" * 32,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 403


def test_twilio_status_callback_assinatura_valida(tmp_path, twilio_request):
    from twilio.request_validator import RequestValidator
    config = replace(
        settings(tmp_path),
        twilio_status_callback_url="https://api.meudominio.com/webhooks/twilio/message-status",
        twilio_validate_signature=True,
    )
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        sid = envio["provedor_id"]

        # Requisição sem assinatura válida é recusada com 403
        dados = {"MessageSid": sid, "MessageStatus": "delivered", "AccountSid": config.twilio_account_sid}
        assert client.post("/webhooks/twilio/message-status", data=dados,
                           headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 403

        # Requisição com assinatura calculada pelo RequestValidator é aceita com 204
        validator = RequestValidator(config.twilio_auth_token)
        signature = validator.compute_signature(config.twilio_status_callback_url, dados)
        assert client.post("/webhooks/twilio/message-status", data=dados, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature,
        }).status_code == 204
        assert client.get(rota).json()[0]["status"] == "ENTREGUE"



def test_fluxo_http_validacao_mensagem_envio_historico_e_duplicidade(tmp_path, twilio_request, monkeypatch):
    monkeypatch.setenv("TWILIO_CONTENT_SID", "HX" + "f" * 32)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "olinda.bcb.gov.br":
            assert request.method == "GET"
            assert request.url.path.endswith("/odata/Metricas(DataBase=@DataBase)")
            assert request.url.params["@DataBase"] == "202606"
            assert request.url.params["$format"] == "json"
            assert request.url.params["$top"] == "200"
            return httpx.Response(200, json=BCB_PAYLOAD)
        pytest.fail("httpx deve acessar somente o BCB")

    config = settings(tmp_path)
    transport = httpx.MockTransport(handler)
    with TestClient(create_app(config, http_transport=transport)) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        assert consulta["status"] == "SUCESSO"
        assert len(requests) == 1
        twilio_request.assert_not_awaited()  # Consultar não envia automaticamente.
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        assert envio["status"] == "NA_FILA"
        assert envio["provedor_id"] == "SM" + "1" * 32
        assert envio["provedor_status"] == "queued"
        payload = twilio_request.call_args.kwargs["data"]
        assert payload["To"] == "whatsapp:+15550000001"
        assert payload["From"] == config.twilio_whatsapp_from
        assert payload["Body"] == consulta["mensagem_gerada"]
        assert "ContentSid" not in payload
        assert envio["mensagem"] == consulta["mensagem_gerada"]
        assert client.post(rota, json={"destinatario": "15550000001"}).json() == envio
        assert client.post(rota, json={"destinatario": "(86) 99999-9999"}).json() == envio
        assert twilio_request.await_count == 1
        assert client.get(rota).json() == [envio]
        assert client.post(rota, json={"destinatario": "inválido"}).status_code == 422
    with TestClient(create_app(config, http_transport=httpx.MockTransport(handler))) as client:
        assert client.post(rota, json=DESTINO).json() == envio
        assert twilio_request.await_count == 1  # Proteção sobrevive ao reinício.


def test_subsegmento_oficial_na_tela_e_na_consulta(tmp_path):
    with TestClient(create_app(settings(tmp_path), http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        pagina = client.get("/")
        assert pagina.status_code == 200
        assert "Ônibus e Micro-ônibus (cód. 21)" in pagina.text
        assert "Outros bens móveis duráveis (eletroeletrônicos, eletrodomésticos, móveis e outros)" in pagina.text
        consulta = client.post("/api/consultas/mercado", json={
            "segmento": "Ônibus e Micro-ônibus (cód. 21)", "periodo": "2026-06",
        }).json()
        assert consulta["status"] == "SUCESSO"
        assert consulta["dados_extraidos"]["cotas_ativas"] == 10680
        assert consulta["dados_extraidos"]["credito_medio"] is None
        assert "Crédito médio:" not in consulta["mensagem_gerada"]


@pytest.mark.parametrize("cenario,status", [
    ("timeout", "INCERTO"), ("connection", "INCERTO"), ("500", "INCERTO"),
    ("400", "ERRO"), ("401", "ERRO"), ("403", "ERRO"), ("429", "ERRO"),
    ("invalid-json", "INCERTO"), ("invalid-schema", "INCERTO"),
])
def test_falhas_whatsapp_persistidas_sem_reenvio(tmp_path, cenario, status, twilio_request):
    async def resposta(*args, **kwargs):
        if cenario == "timeout":
            raise TimeoutError("detalhe privado")
        if cenario == "connection":
            raise ClientConnectionError("detalhe privado")
        if cenario.isdigit():
            return TwilioResponse(int(cenario), json.dumps({"code": 20003, "message": "detalhe privado"}))
        if cenario == "invalid-json":
            return TwilioResponse(201, "não é JSON")
        return TwilioResponse(201, "{}")

    twilio_request.side_effect = resposta
    with TestClient(create_app(settings(tmp_path), http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        assert envio["status"] == status
        assert envio["erro"]
        assert "privado" not in envio["erro"]
        if cenario in {"400", "401", "403", "429"}:
            assert "código Twilio 20003" in envio["erro"]
        assert client.post(rota, json=DESTINO).json() == envio
        assert client.get(rota).json() == [envio]
        assert twilio_request.await_count == 1


@pytest.mark.parametrize("cenario,status", [
    ("timeout", "ERRO"), ("connection", "ERRO"), ("503", "ERRO"),
    ("invalid-json", "ERRO"), ("invalid-schema", "ERRO"), ("empty", "SEM_RESULTADO"),
])
def test_falhas_bcb_rastreaveis_e_sem_envio(tmp_path, cenario, status):
    def handler(request):
        assert request.url.host == "olinda.bcb.gov.br"
        if cenario == "timeout":
            raise httpx.ReadTimeout("simulado", request=request)
        if cenario == "connection":
            raise httpx.ConnectError("simulado", request=request)
        if cenario == "503":
            return httpx.Response(503)
        if cenario == "invalid-json":
            return httpx.Response(200, text="html")
        return httpx.Response(200, json={"value": []} if cenario == "empty" else {"value": "inválido"})

    with TestClient(create_app(settings(tmp_path), http_transport=httpx.MockTransport(handler))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        assert consulta["status"] == status
        assert client.get(f"/api/consultas/{consulta['id']}").json() == consulta
        assert client.post(f"/api/consultas/{consulta['id']}/envios", json=DESTINO).status_code == 409


def test_reserva_simultanea_e_nova_execucao_legitima(tmp_path):
    config = settings(tmp_path)
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        primeiro = client.post("/api/consultas/mercado", json=ENTRADA).json()
        segundo = client.post("/api/consultas/mercado", json={**ENTRADA, "segmento": "Imóveis"}).json()
        engine = create_engine(f"sqlite:///{config.database_path}")
        try:
            repository = SQLiteEnvioRepository(engine)
            with ThreadPoolExecutor(max_workers=2) as pool:
                reservas = list(pool.map(lambda telefone: repository.reservar_envio(primeiro["id"], telefone),
                                         ["15550000001", "5586999999999"]))
            assert sorted(novo for _, novo in reservas) == [False, True]
            assert reservas[0][0].id == reservas[1][0].id
            assert repository.reservar_envio(segundo["id"], "15550000001")[1]
        finally:
            engine.dispose()


def test_erro_persistencia_apos_aceite_nao_permite_segundo_envio(tmp_path, monkeypatch, twilio_request):

    def handler(request):
        if request.url.host == "olinda.bcb.gov.br":
            return httpx.Response(200, json=BCB_PAYLOAD)
        pytest.fail("httpx deve acessar somente o BCB")

    def falhar(*args):
        raise PersistenciaError("Falha de persistência simulada")

    with TestClient(create_app(settings(tmp_path), http_transport=httpx.MockTransport(handler))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        monkeypatch.setattr(SQLiteEnvioRepository, "finalizar_envio", falhar)
        assert client.post(rota, json=DESTINO).status_code == 503
        assert client.post(rota, json=DESTINO).json()["status"] == "ENVIANDO"
        assert twilio_request.await_count == 1


def test_whatsapp_nao_configurado_fica_rastreavel(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / "sem_config.sqlite3"),
                              http_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=BCB_PAYLOAD)))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        envio = client.post(f"/api/consultas/{consulta['id']}/envios", json=DESTINO).json()
        assert envio["status"] == "ERRO"
        assert "não configurado" in envio["erro"]


def test_reserva_de_envio_falha_antes_de_chamar_provedor(tmp_path, monkeypatch):
    def handler(request):
        assert request.url.host == "olinda.bcb.gov.br"
        return httpx.Response(200, json=BCB_PAYLOAD)

    def falhar(*args):
        raise PersistenciaError("Banco indisponível")

    with TestClient(create_app(settings(tmp_path), http_transport=httpx.MockTransport(handler))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        monkeypatch.setattr(SQLiteEnvioRepository, "reservar_envio", falhar)
        assert client.post(f"/api/consultas/{consulta['id']}/envios", json=DESTINO).status_code == 503


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="Chromium opcional para testar a interface")
@pytest.mark.parametrize("destinatario_padrao", ["", "5586999999999"])
def test_interface_consulta_preview_envio_e_historico(tmp_path, twilio_request, destinatario_padrao):
    from playwright.sync_api import expect, sync_playwright

    def handler(request):
        if request.url.host == "olinda.bcb.gov.br":
            return httpx.Response(200, json=BCB_PAYLOAD)
        pytest.fail("httpx deve acessar somente o BCB")

    config = replace(settings(tmp_path), twilio_whatsapp_to=destinatario_padrao)
    with TestClient(create_app(config, http_transport=httpx.MockTransport(handler))) as client:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()

                def route_handler(route):
                    request = route.request
                    if not request.url.startswith("http://testserver/"):
                        route.abort()
                        return
                    response = client.request(request.method, request.url, content=request.post_data,
                                              headers={"Content-Type": "application/json"})
                    route.fulfill(status=response.status_code, body=response.content,
                                  content_type=response.headers.get("content-type", "text/plain"))

                page.route("**/*", route_handler)
                page.goto("http://testserver/")
                page.get_by_label("Tipo de consórcio").select_option("Automóveis")
                page.get_by_label("Período", exact=True).fill("2026-06")
                page.get_by_role("button", name="Consultar Banco Central").click()
                expect(page.locator("#mensagem")).to_contain_text("5.558.340")
                twilio_request.assert_not_awaited()
                expect(page.locator("#ddi-destinatario")).to_have_text("+55")
                expect(page.get_by_label("WhatsApp do destinatário")).to_have_attribute("placeholder", "86 XXXX-XXXX")
                expect(page.get_by_label("WhatsApp do destinatário")).to_have_value(
                    "86 99999-9999" if destinatario_padrao else ""
                )
                if destinatario_padrao:
                    expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_enabled()
                else:
                    expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_disabled()
                page.get_by_label("WhatsApp do destinatário").fill("99999-9999")
                expect(page.locator("#telefone-validacao")).to_contain_text("Informe um número")
                expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_disabled()
                twilio_request.assert_not_awaited()
                page.get_by_label("WhatsApp do destinatário").fill("86 3333-4444")
                expect(page.locator("#telefone-validacao")).to_contain_text("+558633334444")
                expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_enabled()
                page.get_by_label("WhatsApp do destinatário").fill("whatsapp:+55 (86) 99999-9999")
                expect(page.locator("#telefone-validacao")).to_contain_text("+5586999999999")
                page.get_by_label("WhatsApp do destinatário").blur()
                expect(page.get_by_label("WhatsApp do destinatário")).to_have_value("86 99999-9999")
                page.get_by_role("button", name="Enviar WhatsApp").click()
                expect(page.locator("#envio-estado")).to_contain_text("Mensagem aceita")
                expect(page.locator("#envio-historico")).to_contain_text("***9999")
                expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_disabled()
                assert twilio_request.call_args.kwargs["data"]["To"] == "whatsapp:+5586999999999"
                page.reload()
                page.get_by_role("button", name="Ver execução").first.click()
                expect(page.locator("#envio-historico")).to_contain_text("Mensagem aceita")
                expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_disabled()
                assert twilio_request.await_count == 1
            finally:
                browser.close()


def test_twilio_telefone_brasileiro_e_segredo_nao_exposto(tmp_path, twilio_request):
    config = settings(tmp_path)
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        pagina = client.get("/").text
        assert config.twilio_auth_token not in pagina
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        assert client.post(rota, json={"destinatario": "99999-9999"}).status_code == 422
        twilio_request.assert_not_awaited()
        response = client.post(rota, json={"destinatario": "(86) 99999-9999"})
        envio = response.json()
        assert envio["status"] == "NA_FILA"
        assert envio["destinatario"] == "5586999999999"
        assert envio["mensagem"] == consulta["mensagem_gerada"]
        assert twilio_request.call_args.kwargs["data"]["To"] == "whatsapp:+5586999999999"
        assert client.get(rota).json() == [envio]
        assert config.twilio_auth_token not in response.text
        assert config.twilio_account_sid not in response.text
        assert client.post(rota, json={"destinatario": "+55 86 99999-9999"}).json() == envio
        assert twilio_request.await_count == 1


def test_falha_retornada_pela_twilio_preserva_sid_e_status(tmp_path, twilio_request):
    twilio_request.side_effect = None
    twilio_request.return_value = TwilioResponse(201, json.dumps({
        "sid": "SM" + "2" * 32, "status": "failed", "to": "whatsapp:+15550000001",
        "error_code": 63015, "error_message": "detalhe privado",
    }))
    with TestClient(create_app(settings(tmp_path), http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        assert envio["status"] == "FALHOU"
        assert envio["provedor_status"] == "failed"
        assert envio["provedor_id"] == "SM" + "2" * 32
        assert "privado" not in envio["erro"]
        assert client.get(rota).json() == [envio]
        assert client.post(rota, json=DESTINO).json() == envio
        assert twilio_request.await_count == 1


def test_migracao_preserva_envio_anterior_e_pode_reiniciar(tmp_path):
    config = settings(tmp_path)
    engine = create_engine(f"sqlite:///{config.database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("""CREATE TABLE envios (
                id VARCHAR(36) PRIMARY KEY, execucao_id VARCHAR(36), destinatario VARCHAR(15),
                mensagem VARCHAR, status VARCHAR, data_hora FLOAT, finalizado_em FLOAT,
                provedor_id VARCHAR, erro VARCHAR, tentativas INTEGER,
                UNIQUE (execucao_id, destinatario))"""))
            connection.execute(text("""INSERT INTO envios
                (id, execucao_id, destinatario, mensagem, status, data_hora, provedor_id, tentativas)
                VALUES ('antigo', 'consulta-antiga', '15550000001', 'Mensagem anterior', 'ACEITO', 1, 'id-anterior', 1)"""))
        for _ in range(2):
            with TestClient(create_app(config)) as client:
                envio = client.get("/api/consultas/consulta-antiga/envios").json()[0]
                assert envio["id"] == "antigo"
                assert envio["mensagem"] == "Mensagem anterior"
                assert envio["provedor_id"] == "id-anterior"
                assert envio["provedor_status"] is None
                assert client.post("/api/consultas/consulta-antiga/envios", json=DESTINO).json() == envio
    finally:
        engine.dispose()


def test_demo_try_out_whatsapp_com_content_sid_preserva_consulta_e_mensagem_enviada(tmp_path, twilio_request):
    config = replace(
        settings(tmp_path),
        twilio_production_sender=False,
        twilio_content_sid="HX" + "e" * 32,
        twilio_panorama_content_sid="",
    )
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        assert consulta["status"] == "SUCESSO"
        assert consulta["mensagem_gerada"] is not None

        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        assert envio["status"] == "NA_FILA"
        assert envio["provedor_id"] == "SM" + "1" * 32
        assert envio["mensagem"] == consulta["mensagem_gerada"]
        assert "HXe" in (envio["mensagem_enviada"] or "")

        payload = twilio_request.call_args.kwargs["data"]
        assert payload["ContentSid"] == "HX" + "e" * 32
        assert "Body" not in payload

        # A consulta no banco permanece com status SUCESSO
        consulta_recuperada = client.get(f"/api/consultas/{consulta['id']}").json()
        assert consulta_recuperada["status"] == "SUCESSO"
        assert consulta_recuperada["mensagem_gerada"] == consulta["mensagem_gerada"]


def test_demo_try_out_whatsapp_sem_content_sid_retorna_erro_controlado_e_preserva_consulta(tmp_path, twilio_request):
    config = replace(
        settings(tmp_path),
        twilio_production_sender=False,
        twilio_content_sid="",
        twilio_panorama_content_sid="",
    )
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        assert consulta["status"] == "SUCESSO"

        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        assert envio["status"] == "FALHOU"
        assert "Envio WhatsApp indisponível no ambiente de demonstração" in envio["erro"]
        assert "TWILIO_CONTENT_SID" in envio["erro"]
        twilio_request.assert_not_awaited()

        # Falha de WhatsApp não afeta o sucesso da consulta
        consulta_recuperada = client.get(f"/api/consultas/{consulta['id']}").json()
        assert consulta_recuperada["status"] == "SUCESSO"
        assert consulta_recuperada["mensagem_gerada"] == consulta["mensagem_gerada"]


def test_demo_try_out_whatsapp_erro_21654_preserva_consulta_e_registra_falhou(tmp_path, twilio_request):
    twilio_request.side_effect = None
    twilio_request.return_value = TwilioResponse(400, json.dumps({
        "code": 21654,
        "message": "ContentSid Required",
        "status": 400,
    }))
    config = replace(
        settings(tmp_path),
        twilio_production_sender=False,
        twilio_content_sid="HX" + "d" * 32,
        twilio_panorama_content_sid="",
    )
    with TestClient(create_app(config, http_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BCB_PAYLOAD)
    ))) as client:
        consulta = client.post("/api/consultas/mercado", json=ENTRADA).json()
        assert consulta["status"] == "SUCESSO"

        rota = f"/api/consultas/{consulta['id']}/envios"
        envio = client.post(rota, json=DESTINO).json()
        assert envio["status"] == "FALHOU"
        assert envio["error_code"] == 21654
        assert "Try out WhatsApp" in envio["erro"]
        assert "código Twilio 21654" in envio["erro"]
        assert "ContentSid Required" not in envio["erro"]  # Sem expor payload cru

        # A consulta continua com status SUCESSO e mensagem gerada intacta
        consulta_recuperada = client.get(f"/api/consultas/{consulta['id']}").json()
        assert consulta_recuperada["status"] == "SUCESSO"
        assert consulta_recuperada["mensagem_gerada"] == consulta["mensagem_gerada"]

