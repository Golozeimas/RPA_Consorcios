"""Smoke test opt-in: HTTP + BCB real + API + SQLite temporário."""

import os

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.mark.skipif(os.getenv("RUN_LIVE_BCB") != "1", reason="Ative RUN_LIVE_BCB=1 para consultar a fonte real")
def test_consulta_real_sem_envio(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / "bcb.sqlite3"))) as client:
        response = client.post("/api/consultas/mercado", json={
            "administradora": "PEDIDO DE DEMONSTRAÇÃO SEM ATRIBUIÇÃO", "periodo": None,
        })
        assert response.status_code == 200
        execucao = response.json()
        assert execucao["status"] == "SUCESSO", execucao.get("erro")
        resultado = execucao["dados_extraidos"]
        assert resultado["periodo_referencia"] >= "2015-12"
        assert resultado["administradora"] is None
        assert resultado["cotas_ativas"] > 0
        assert resultado["creditos_comercializados"] is None
        assert "administradora" in resultado["campos_indisponiveis"]
        assert "Dados agregados do mercado" in execucao["mensagem_gerada"]
        assert "PEDIDO DE DEMONSTRAÇÃO" not in execucao["mensagem_gerada"]
        assert client.get(f"/api/consultas/{execucao['id']}").json() == execucao
