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


def settings(tmp_path):
    return Settings(database_path=tmp_path / "http.sqlite3", twilio_auth_token="token-ficticio-de-teste",
                    twilio_account_sid="AC" + "0" * 32, twilio_whatsapp_from="whatsapp:+15550000002")


def test_fluxo_http_validacao_mensagem_envio_historico_e_duplicidade(tmp_path, twilio_request):
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
        assert envio["status"] == "ACEITO"
        assert envio["provedor_id"] == "SM" + "1" * 32
        assert envio["provedor_status"] == "queued"
        payload = twilio_request.call_args.kwargs["data"]
        assert payload["To"] == "whatsapp:+15550000001"
        assert payload["From"] == config.twilio_whatsapp_from
        assert payload["Body"] == consulta["mensagem_gerada"]
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
                expect(page.get_by_label("WhatsApp do destinatário")).to_have_value(destinatario_padrao)
                if destinatario_padrao:
                    expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_enabled()
                else:
                    expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_disabled()
                page.get_by_label("WhatsApp do destinatário").fill("99999-9999")
                expect(page.locator("#telefone-validacao")).to_contain_text("Informe um número")
                expect(page.get_by_role("button", name="Enviar WhatsApp")).to_be_disabled()
                twilio_request.assert_not_awaited()
                page.get_by_label("WhatsApp do destinatário").fill("whatsapp:+55 (86) 99999-9999")
                expect(page.locator("#telefone-validacao")).to_contain_text("+5586999999999")
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
        assert envio["status"] == "ACEITO"
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
        assert envio["status"] == "ERRO"
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
