import logging

from playwright.async_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeout, async_playwright

from app.domain import Consulta, ExtracaoError, FonteIndisponivelError, NavegacaoError

PORTAL_URL = "https://dadosabertos.bcb.gov.br/dataset/dados-agregados-do-segmento-de-consorcios"
NAVEGADOR_URL = "https://olinda.bcb.gov.br/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1/aplicacao#!/"
ODATA_METRICAS = "https://olinda.bcb.gov.br/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1/odata/Metricas("
MAXIMO_REGISTROS = 200
logger = logging.getLogger(__name__)


class BCBConsorciosRpa:
    def __init__(self, timeout_ms: int = 30000, headless: bool = True) -> None:
        self.timeout_ms = timeout_ms
        self.headless = headless

    async def extrair(self, consulta: Consulta) -> str:
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context(locale="pt-BR")
                    context.set_default_timeout(self.timeout_ms)
                    page = await context.new_page()
                    logger.info("bcb_abertura periodo=%s", consulta.periodo)
                    resposta = await page.goto(PORTAL_URL, wait_until="domcontentloaded")
                    if resposta is None or not resposta.ok:
                        raise FonteIndisponivelError("O portal do BCB está indisponível.")
                    logger.info("bcb_navegacao periodo=%s", consulta.periodo)
                    recurso = page.locator("li.resource-item").filter(
                        has=page.locator('a[title="API - Navegador de Dados"]')
                    )
                    await recurso.get_by_role("link", name="Explorar").click()
                    async with page.expect_popup() as popup:
                        await recurso.locator(f'a[href="{NAVEGADOR_URL}"]').click()
                    navegador = await popup.value
                    await navegador.get_by_role("link", name="Métricas", exact=True).click()
                    return await self._consultar_pagina(navegador, consulta)
                finally:
                    await browser.close()
        except PlaywrightTimeout as exc:
            raise NavegacaoError("O BCB demorou a responder ou um elemento esperado não foi encontrado.") from exc
        except PlaywrightError as exc:
            raise NavegacaoError("Não foi possível abrir ou navegar na consulta do BCB.") from exc

    async def _consultar_pagina(self, page: Page, consulta: Consulta) -> str:
        await page.locator("#param0").fill(consulta.data_base)
        
        await page.locator('input[ng-model="formulario.$top"]').fill(str(MAXIMO_REGISTROS))
        
        async with page.expect_response(
            lambda response: response.url.startswith(ODATA_METRICAS)
            and response.request.method == "GET"
        ) as resposta_pendente:
            await page.get_by_role("button", name="Executar", exact=True).click()
        
        resposta = await resposta_pendente.value
        
        if not resposta.ok:
            logger.warning("bcb_http_falha status=%s", resposta.status)
            raise FonteIndisponivelError("O BCB não conseguiu carregar os dados. Tente novamente mais tarde.")
        
        # A resposta é somente uma condição de sincronização. A extração vem do DOM.
        await page.locator(".loader:visible").wait_for(state="hidden")
        await page.get_by_role("tab", name="JSON", exact=True).click()
        resultado = page.locator("pre.dados:visible")
        await resultado.wait_for(state="visible")
        texto = (await resultado.inner_text()).strip()
        if not texto.startswith("{"):
            raise ExtracaoError("O resultado exibido pelo BCB não está no formato esperado.")
        if await page.locator("pre.alert-danger:visible").count():
            raise ExtracaoError("A página do BCB apresentou um erro na consulta.")
        if await page.get_by_text("Há mais registros além dos que estão exibidos.", exact=False).is_visible():
            raise ExtracaoError("O BCB retornou dados parciais; a consulta precisa ser revista.")
        logger.info("bcb_extraido periodo=%s", consulta.periodo)
        return texto
