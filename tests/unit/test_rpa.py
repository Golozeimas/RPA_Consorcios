import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout
import pytest

from app.automation.bcb_consorcios import BCBConsorciosRpa
from app.domain import Consulta, FonteIndisponivelError, NavegacaoError


@pytest.mark.parametrize("failure", [PlaywrightTimeout("timeout"), PlaywrightError("navigation failed")])
def test_falha_navegacao_traduzida_e_browser_fechado(failure):
    page = MagicMock()
    page.goto = AsyncMock(side_effect=failure)
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=False)
    with patch("app.automation.bcb_consorcios.async_playwright", return_value=manager):
        with pytest.raises(NavegacaoError):
            asyncio.run(BCBConsorciosRpa().extrair(Consulta("2025-12")))
    browser.close.assert_awaited_once()


def test_http_falha_na_consulta_nao_extrai_resultado():
    page = MagicMock()
    page.locator.return_value.fill = AsyncMock()
    page.get_by_role.return_value.click = AsyncMock()
    response = MagicMock(ok=False, status=503)

    async def pending_response():
        return response

    async def run():
        pending = MagicMock()
        pending.value = pending_response()
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=pending)
        manager.__aexit__ = AsyncMock(return_value=False)
        page.expect_response.return_value = manager
        with pytest.raises(FonteIndisponivelError):
            await BCBConsorciosRpa()._consultar_pagina(page, Consulta("2025-12"))

    asyncio.run(run())
    page.locator.assert_any_call("#param0")


def test_coletor_odata_fecha_browser_quando_navegacao_expira():
    page = MagicMock()
    page.goto = AsyncMock(side_effect=PlaywrightTimeout("timeout"))
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=False)
    with patch("app.automation.bcb_consorcios.async_playwright", return_value=manager):
        with pytest.raises(NavegacaoError):
            asyncio.run(BCBConsorciosRpa().extrair_periodo("2026-06"))
    browser.close.assert_awaited_once()
