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
            "segmento": "Automóveis", "periodo": None,
        })
        assert response.status_code == 200
        execucao = response.json()
        assert execucao["status"] == "SUCESSO", execucao.get("erro")
        resultado = execucao["dados_extraidos"]
        assert resultado["periodo_referencia"] >= "2015-12"
        assert resultado["segmento"] == "Automóveis"
        assert resultado["cotas_ativas"] > 0
        assert resultado["credito_medio"] is not None
        assert resultado["prazo_medio"] is not None
        assert resultado["taxa_administracao_media"] is not None
        assert resultado["contemplacoes"] is not None
        assert "administradora" not in resultado
        assert "Panorama do mercado" in execucao["mensagem_gerada"]
        assert client.get(f"/api/consultas/{execucao['id']}").json() == execucao
