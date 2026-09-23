"""Chromium real com resposta local interceptada, sem depender do BCB."""

import asyncio
import json
import os

from playwright.async_api import async_playwright
import pytest

from app.automation.bcb_consorcios import BCBConsorciosRpa, ODATA_METRICAS
from app.domain import Consulta, ExtracaoError
from app.services.bcb_service import normalizar_resultado

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="Ative RUN_BROWSER_TESTS=1 com Chromium instalado")

HTML = """<!doctype html><html><body>
<input id="param0"><input ng-model="formulario.$top">
<button id="executar">Executar</button>
<div class="loader" hidden>Carregando</div>
<button role="tab" onclick="document.querySelector('pre').hidden=false">JSON</button>
<pre class="dados" hidden></pre>
<script>
document.querySelector('#executar').onclick = async () => {
 const loader = document.querySelector('.loader'); loader.hidden = false;
 const r = await fetch('/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1/odata/Metricas(DataBase=@DataBase)?@DataBase=' + document.querySelector('#param0').value);
 document.querySelector('pre').textContent = await r.text();
 loader.hidden = true;
};
</script></body></html>"""


@pytest.mark.parametrize("body,expected", [(json.dumps({"value": []}), None), ("invalid", "error")])
def test_dom_json_e_loading_com_chromium(body, expected):
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                async def route_handler(route):
                    if route.request.url.startswith(ODATA_METRICAS):
                        await route.fulfill(status=200, content_type="application/json", body=body)
                    else:
                        await route.fulfill(status=200, content_type="text/html", body=HTML)
                await page.route("**/*", route_handler)
                await page.goto("https://olinda.bcb.gov.br/fixture")
                if expected == "error":
                    with pytest.raises(ExtracaoError):
                        await BCBConsorciosRpa()._consultar_pagina(page, Consulta("2025-12"))
                else:
                    bruto = await BCBConsorciosRpa()._consultar_pagina(page, Consulta("2025-12"))
                    assert normalizar_resultado(bruto, Consulta("2025-12")) is None
            finally:
                await browser.close()
    asyncio.run(run())
