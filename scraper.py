import os
import json
from datetime import datetime
from playwright.async_api import async_playwright


async def scrape_tiktok_profile(username: str, max_scrolls: int = 3):
    username = username.lstrip("@")
    url = f"https://www.tiktok.com/@{username}"
    posts_capturados = {}

    es_servidor_nube = os.environ.get("RENDER") or os.environ.get("SPACE_ID") or os.environ.get("HEADLESS") == "1"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=bool(es_servidor_nube),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )

        page = await context.new_page()

        async def interceptar_respuestas(response):
            if "/api/post/item_list/" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    for item in data.get("itemList", []):
                        video_id = item.get("id")
                        if video_id:
                            ts = item.get("createTime", 0)
                            fecha_str = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M") if ts else "N/A"
                            posts_capturados[video_id] = {
                                "id": video_id,
                                "descripcion": item.get("desc", ""),
                                "fecha": fecha_str,
                                "url": f"https://www.tiktok.com/@{username}/video/{video_id}",
                                "estadisticas": {
                                    "vistas": item.get("stats", {}).get("playCount", 0),
                                    "likes": item.get("stats", {}).get("diggCount", 0),
                                    "comentarios": item.get("stats", {}).get("commentCount", 0),
                                    "compartidos": item.get("stats", {}).get("shareCount", 0),
                                }
                            }
                except Exception:
                    pass

        page.on("response", interceptar_respuestas)

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        hydration_script = await page.query_selector('script#__UNIVERSAL_DATA_FOR_REHYDRATION__')
        if hydration_script:
            raw_json = await hydration_script.inner_text()
            data_hidratacion = json.loads(raw_json)
            user_detail = data_hidratacion.get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {})

            if user_detail.get("statusCode", 0) != 0:
                await browser.close()
                return {"estado": "no_existe", "usuario": username, "posts": []}

            if user_detail.get("userInfo", {}).get("user", {}).get("privateAccount"):
                await browser.close()
                return {"estado": "privada", "usuario": username, "posts": []}

        for _ in range(max_scrolls):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)

        elementos_dom = await page.query_selector_all('[data-e2e="user-post-item"]')
        for el in elementos_dom:
            link_el = await el.query_selector('a')
            vistas_el = await el.query_selector('[data-e2e="video-views"]')
            if link_el:
                href = await link_el.get_attribute("href")
                if href and "/video/" in href:
                    vid_id = href.split("/video/")[-1].split("?")[0]
                    if vid_id not in posts_capturados:
                        vistas = await vistas_el.inner_text() if vistas_el else "N/A"
                        posts_capturados[vid_id] = {
                            "id": vid_id,
                            "descripcion": "Vista previa HTML",
                            "fecha": "Reciente",
                            "url": href,
                            "estadisticas": {"vistas": vistas, "likes": "-", "comentarios": "-", "compartidos": "-"}
                        }

        await browser.close()

        return {
            "estado": "ok",
            "usuario": username,
            "publica": True,
            "total_posts_extraidos": len(posts_capturados),
            "posts": list(posts_capturados.values())
        }