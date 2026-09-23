import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine

from app.core.config import Settings
from app.domain import Consulta, DATASET, DadosInvalidosError, FONTE, METRICA, NavegacaoError, PersistenciaError, Resultado, Status
from app.main import create_app
from app.models.execucao import Base
from app.repositories.execucao_repository import SQLiteExecutionRepository
from app.services.consulta_service import ConsultaService


class FakeBCB:
    def __init__(self, outcome="success"):
        self.calls = 0
        self.outcome = outcome

    async def consultar(self, consulta):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome == "empty":
            return None
        return Resultado(FONTE, DATASET, consulta.periodo, METRICA, Decimal("12821.11"), "mil", datetime.now(timezone.utc))


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'teste.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield SQLiteExecutionRepository(engine)
    engine.dispose()


def test_sucesso_persistido_e_duplicata_rastreavel(tmp_path):
    gateway = FakeBCB()
    app = create_app(Settings(database_path=tmp_path / "app.sqlite3"), gateway)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/consulta.js").status_code == 200
        first = client.post("/api/consultas", json={"periodo": "2025-12"}).json()
        assert first["status"] == "SUCESSO"
        assert first["dados_extraidos"]["valor"] == "12821.11"
        duplicate = client.post("/api/consultas", json={"periodo": "2025-12"}).json()
        assert duplicate["status"] == "DUPLICADA"
        assert duplicate["duplicada_de"] == first["id"]
        assert gateway.calls == 1
        assert len(client.get("/api/consultas").json()) == 2
        assert client.get(f"/api/consultas/{first['id']}").json() == first
        assert client.get("/api/consultas/inexistente").status_code == 404
        assert client.post("/api/consultas", json={"periodo": "2025-13"}).status_code == 422
    with TestClient(create_app(Settings(database_path=tmp_path / "app.sqlite3"), gateway)) as client:
        assert len(client.get("/api/consultas").json()) == 2


@pytest.mark.parametrize("outcome,status", [
    ("empty", Status.SEM_RESULTADO), (NavegacaoError("Falha controlada"), Status.ERRO),
    (DadosInvalidosError("Dados inválidos"), Status.ERRO), (RuntimeError("detalhe interno"), Status.ERRO),
    (TimeoutError(), Status.ERRO),
])
def test_falhas_e_ausencia_rastreaveis(repository, outcome, status):
    execucao = asyncio.run(ConsultaService(FakeBCB(outcome), repository).executar(Consulta("2025-12")))
    assert execucao.status == status
    assert repository.obter(execucao.id).status == status
    assert "detalhe interno" not in (execucao.erro or "")
    assert execucao.dados_extraidos is None


def test_duas_reservas_simultaneas_so_uma_processa(repository):
    def reservar(_):
        return repository.reservar(Consulta("2025-12"), datetime.now(timezone.utc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(reservar, range(2)))
    assert sorted(r.status for r in resultados) == [Status.DUPLICADA, Status.PROCESSANDO]
    assert len(repository.listar()) == 2


def test_nova_consulta_permitida_apos_janela(repository):
    agora = datetime.now(timezone.utc)
    first = repository.reservar(Consulta("2025-12"), agora)
    repository.finalizar(first.id, Status.SEM_RESULTADO, None, None)
    later = repository.reservar(Consulta("2025-12"), agora + timedelta(seconds=31))
    assert later.status == Status.PROCESSANDO
    assert later.id != first.id


def test_execucao_interrompida_expira_com_historico(repository):
    agora = datetime.now(timezone.utc)
    first = repository.reservar(Consulta("2025-12"), agora - timedelta(seconds=200))
    repository.reservar(Consulta("2025-12"), agora)
    assert repository.obter(first.id).status == Status.ERRO
    later = repository.reservar(Consulta("2025-12"), agora + timedelta(seconds=31))
    assert later.status == Status.PROCESSANDO


def test_persistencia_indisponivel_nao_executa_rpa(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sem_tabelas.sqlite3'}")
    gateway = FakeBCB()
    try:
        service = ConsultaService(gateway, SQLiteExecutionRepository(engine))
        with pytest.raises(PersistenciaError):
            asyncio.run(service.executar(Consulta("2025-12")))
        assert gateway.calls == 0
    finally:
        engine.dispose()


def test_falha_finalizacao_preserva_reserva(repository, monkeypatch):
    def falhar(*args):
        raise PersistenciaError("Falha ao gravar")
    monkeypatch.setattr(repository, "finalizar", falhar)
    with pytest.raises(PersistenciaError):
        asyncio.run(ConsultaService(FakeBCB(), repository).executar(Consulta("2025-12")))
    assert repository.listar()[0].status == Status.PROCESSANDO


def test_prazo_total_interrompe_gateway_e_registra_erro(repository):
    class Bloqueado:
        async def consultar(self, consulta):
            await asyncio.Event().wait()
    execucao = asyncio.run(ConsultaService(Bloqueado(), repository, timeout_seconds=0).executar(Consulta("2025-12")))
    assert execucao.status == Status.ERRO
    assert "tempo máximo" in execucao.erro
    assert repository.obter(execucao.id).status == Status.ERRO


def test_cancelamento_preserva_historico(repository):
    class Cancelado:
        async def consultar(self, consulta):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ConsultaService(Cancelado(), repository).executar(Consulta("2025-12")))
    assert repository.listar()[0].status == Status.ERRO


def test_api_retorna_503_controlado_se_reserva_falha(tmp_path, monkeypatch):
    def falhar(*args):
        raise PersistenciaError("Não foi possível registrar a consulta no banco de dados.")
    monkeypatch.setattr(SQLiteExecutionRepository, "reservar", falhar)
    gateway = FakeBCB()
    with TestClient(create_app(Settings(database_path=tmp_path / "falha.sqlite3"), gateway)) as client:
        response = client.post("/api/consultas", json={"periodo": "2025-12"})
        assert response.status_code == 503
        assert "banco de dados" in response.json()["detail"]
        assert gateway.calls == 0
