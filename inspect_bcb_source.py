import json
import re
import httpx
import asyncio
from playwright.async_api import async_playwright

BASE = "https://olinda.bcb.gov.br/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1"
with httpx.Client(timeout=60) as client:
    html = client.get(f"{BASE}/documentacao").content.decode("utf-8")
    print("DOC STATUS", len(html))
    marker = html.index('"recursos" : [')
    start = html.rfind('"servico" : {', 0, marker)
    specification, _ = json.JSONDecoder().raw_decode("{" + html[start:])
    for resource in specification["recursos"]:
        print("RESOURCE", resource["localizacao"]["nome"])
        print("PARAMS", [(p["localizacao"]["nome"], p["tipo"], p.get("opcional")) for p in resource["parametros"]])
        print("FIELDS", [(p["localizacao"]["nome"], p["tipo"]) for p in resource["tipo"]["propriedades"]])
    for period in (202606, 202603, 202512, 202609, 202506):
        url = f"{BASE}/odata/Metricas(DataBase=@DataBase)?@DataBase={period}&$top=200&$format=json"
        response = client.get(url)
        print("PERIOD", period, response.status_code)
        if response.is_success:
            payload = response.json()
            print("COUNT", len(payload.get("value", [])), "NEXT", payload.get("@odata.nextLink"))
            for item in payload.get("value", []):
                if item.get("IdMetrica") in {"9", "10", "28", "54", "85", "114"}:
                    print("METRIC", item)
    print("DOC admin occurrences", len(re.findall("administradora", html, re.I)))


async def browser_check():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            url = f"{BASE}/odata/Metricas(DataBase=@DataBase)?@DataBase=202606&$top=200&$format=json"
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("BROWSER", response.status, response.url, len(await response.body()),
                  (await page.locator("body").inner_text())[:180])
        finally:
            await browser.close()


asyncio.run(browser_check())
