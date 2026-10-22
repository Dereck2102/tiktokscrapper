"""Playwright-based TikTok profile scraping module."""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Response, async_playwright

BASE_DIR = Path(__file__).resolve().parent
PERFIL_NAVEGADOR_DIR = BASE_DIR / "data" / "browser_profile"

USER_AGENTS: dict[str, str] = {
    "chrome_windows": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "chrome_mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "edge_windows": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0"
    ),
}

MODOS: tuple[str, ...] = ("hibrido", "red", "dom", "rapido")

SELECTOR_POST = '[data-e2e="user-post-item"]'
SELECTOR_HIDRATACION = "script#__UNIVERSAL_DATA_FOR_REHYDRATION__"
SELECTORES_CAPTCHA: tuple[str, ...] = (
    "#captcha-verify-container-main-page",
    "#captcha_container",
    "div[class*='captcha_verify']",
    "div[class*='CaptchaVerify']",
)

JS_LEER_DOM = """
(sel) => Array.from(document.querySelectorAll(sel)).map(el => {
    const a = el.querySelector('a');
    const v = el.querySelector('[data-e2e="video-views"]');
    const img = el.querySelector('img');
    return {
        href: a ? a.href : null,
        vistas: v ? v.innerText : null,
        alt: img ? img.getAttribute('alt') : null,
        portada: img ? img.getAttribute('src') : null,
        fijado: !!el.querySelector('[data-e2e="video-card-badge"]'),
    };
})
"""

ProgressCallback = Optional[Callable[[int, str], None]]


@dataclass(frozen=True)
class ScrapeOptions:
    """Configuration parameters for a profile scraping execution."""

    modo: str = "hibrido"
    max_scrolls: int = 5
    max_posts: int = 0
    scroll_delay_ms: int = 2500
    headless: bool = True
    bloquear_multimedia: bool = True
    sesion_persistente: bool = False
    humanizar: bool = True
    detener_sin_nuevos: int = 3
    fecha_desde: Optional[str] = None
    user_agent: str = "chrome_windows"
    timeout_carga_s: int = 25
    reintentos: int = 2

    @classmethod
    def desde_dict(cls, data: Optional[dict[str, Any]]) -> ScrapeOptions:
        """Creates a validated ScrapeOptions instance from a raw dictionary."""
        raw = data or {}

        def _parse_int(key: str, default: int, minimum: int, maximum: int) -> int:
            try:
                return max(minimum, min(int(raw.get(key, default)), maximum))
            except (TypeError, ValueError):
                return default

        def _parse_bool(key: str, default: bool) -> bool:
            val = raw.get(key, default)
            if isinstance(val, str):
                return val.lower() in ("1", "true", "on", "si", "sí", "yes")
            return bool(val)

        modo = raw.get("modo", "hibrido")
        fecha = (raw.get("fecha_desde") or "").strip() or None
        if fecha:
            try:
                datetime.strptime(fecha, "%Y-%m-%d")
            except ValueError:
                fecha = None
        ua = raw.get("user_agent", "chrome_windows")

        return cls(
            modo=modo if modo in MODOS else "hibrido",
            max_scrolls=_parse_int("max_scrolls", 5, 0, 200),
            max_posts=_parse_int("max_posts", 0, 0, 5000),
            scroll_delay_ms=_parse_int("scroll_delay_ms", 2500, 500, 15000),
            headless=_parse_bool("headless", True),
            bloquear_multimedia=_parse_bool("bloquear_multimedia", True),
            sesion_persistente=_parse_bool("sesion_persistente", False),
            humanizar=_parse_bool("humanizar", True),
            detener_sin_nuevos=_parse_int("detener_sin_nuevos", 3, 1, 50),
            fecha_desde=fecha,
            user_agent=ua if ua in USER_AGENTS else "chrome_windows",
            timeout_carga_s=_parse_int("timeout_carga_s", 25, 5, 120),
            reintentos=_parse_int("reintentos", 2, 0, 5),
        )


class TikTokDataParser:
    """Transforms raw TikTok API payloads and DOM structures into normalized records."""

    @staticmethod
    def parse_count(value: Any) -> Optional[int]:
        """Parses compact numeric strings (e.g., '1.2M', '15K') into integers."""
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip().upper().replace(" ", "")
        if not text:
            return None
        multiplier = 1
        if text.endswith("K"):
            multiplier, text = 1_000, text[:-1]
        elif text.endswith("M"):
            multiplier, text = 1_000_000, text[:-1]
        elif text.endswith("B"):
            multiplier, text = 1_000_000_000, text[:-1]
        text = text.replace(",", ".")
        if text.count(".") > 1:
            text = text.replace(".", "")
        try:
            return int(float(text) * multiplier)
        except ValueError:
            return None

    @classmethod
    def to_int(cls, value: Any) -> Optional[int]:
        """Converts an arbitrary value into an integer if possible."""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return cls.parse_count(value)

    @staticmethod
    def extract_hashtags(item: dict[str, Any], description: str) -> list[str]:
        """Extracts unique lowercase hashtags from API metadata or caption text."""
        tags: list[str] = []
        for extra in item.get("textExtra") or []:
            name = extra.get("hashtagName")
            if name:
                tags.append(name.lower())
        if not tags:
            for challenge in item.get("challenges") or []:
                if challenge.get("title"):
                    tags.append(challenge["title"].lower())
        if not tags and description:
            tags = [h.lower() for h in re.findall(r"#(\w+)", description)]
        return list(dict.fromkeys(tags))

    @staticmethod
    def extract_mentions(item: dict[str, Any], description: str) -> list[str]:
        """Extracts unique user mentions from API metadata or caption text."""
        mentions = [
            extra.get("userUniqueId")
            for extra in item.get("textExtra") or []
            if extra.get("userUniqueId")
        ]
        if not mentions and description:
            mentions = re.findall(r"@([\w.]+)", description)
        return list(dict.fromkeys(mentions))

    @classmethod
    def parse_api_item(cls, item: dict[str, Any], username: str) -> dict[str, Any]:
        """Normalizes an item from TikTok's item_list payload."""
        video_id = str(item.get("id", ""))
        ts = cls.to_int(item.get("createTime")) or 0
        desc = item.get("desc", "") or ""
        stats = item.get("stats") or {}
        stats_v2 = item.get("statsV2") or {}
        video = item.get("video") or {}
        music = item.get("music") or {}
        is_photo = bool(item.get("imagePost"))

        def _stat(key: str) -> Optional[int]:
            val = cls.to_int(stats_v2.get(key))
            return val if val is not None else cls.to_int(stats.get(key))

        return {
            "id": video_id,
            "descripcion": desc,
            "timestamp": ts,
            "fecha": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else None,
            "url": f"https://www.tiktok.com/@{username}/{'photo' if is_photo else 'video'}/{video_id}",
            "tipo": "foto" if is_photo else "video",
            "duracion": cls.to_int(video.get("duration")) or 0,
            "fijado": bool(item.get("isPinnedItem") or item.get("isPinned")),
            "hashtags": cls.extract_hashtags(item, desc),
            "menciones": cls.extract_mentions(item, desc),
            "musica": {
                "titulo": music.get("title"),
                "autor": music.get("authorName"),
                "original": bool(music.get("original")),
            },
            "portada": video.get("cover") or video.get("originCover"),
            "estadisticas": {
                "vistas": _stat("playCount"),
                "likes": _stat("diggCount"),
                "comentarios": _stat("commentCount"),
                "compartidos": _stat("shareCount"),
                "guardados": _stat("collectCount"),
            },
            "fuente": "api",
        }

    @classmethod
    def parse_dom_item(cls, raw: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Normalizes a post node extracted from the rendered DOM."""
        href = raw.get("href") or ""
        match = re.search(r"/(video|photo)/(\d+)", href)
        if not match:
            return None
        desc = raw.get("alt") or ""
        return {
            "id": match.group(2),
            "descripcion": desc,
            "timestamp": None,
            "fecha": None,
            "url": href.split("?")[0],
            "tipo": "foto" if match.group(1) == "photo" else "video",
            "duracion": None,
            "fijado": bool(raw.get("fijado")),
            "hashtags": list(dict.fromkeys(h.lower() for h in re.findall(r"#(\w+)", desc))),
            "menciones": [],
            "musica": {"titulo": None, "autor": None, "original": None},
            "portada": raw.get("portada"),
            "estadisticas": {
                "vistas": cls.parse_count(raw.get("vistas")),
                "likes": None,
                "comentarios": None,
                "compartidos": None,
                "guardados": None,
            },
            "fuente": "dom",
        }

    @classmethod
    def parse_profile(cls, user_detail: dict[str, Any]) -> dict[str, Any]:
        """Normalizes profile metadata from hydration scope."""
        info = user_detail.get("userInfo") or {}
        user = info.get("user") or {}
        stats = info.get("statsV2") or info.get("stats") or {}
        stats_v1 = info.get("stats") or {}

        def _stat(key: str, fallback: Optional[str] = None) -> Optional[int]:
            val = cls.to_int(stats.get(key))
            if val is None and fallback:
                val = cls.to_int(stats.get(fallback))
            if val is None:
                val = cls.to_int(stats_v1.get(key)) or (
                    cls.to_int(stats_v1.get(fallback)) if fallback else None
                )
            return val

        return {
            "id": user.get("id"),
            "usuario": user.get("uniqueId"),
            "nombre": user.get("nickname"),
            "bio": user.get("signature"),
            "avatar": user.get("avatarLarger") or user.get("avatarMedium"),
            "verificado": bool(user.get("verified")),
            "privada": bool(user.get("privateAccount")),
            "enlace_bio": (user.get("bioLink") or {}).get("link"),
            "region": user.get("region"),
            "seguidores": _stat("followerCount"),
            "siguiendo": _stat("followingCount"),
            "likes_totales": _stat("heartCount", "heart"),
            "videos": _stat("videoCount"),
            "amigos": _stat("friendCount"),
        }


class ExtractionStrategy(ABC):
    """Strategy contract defining how posts are collected from a TikTok profile page."""

    def __init__(self, parser: TikTokDataParser) -> None:
        self._parser = parser

    @property
    @abstractmethod
    def uses_network(self) -> bool:
        """Indicates whether this strategy captures network API responses."""

    @property
    @abstractmethod
    def uses_dom(self) -> bool:
        """Indicates whether this strategy extracts post cards from the DOM."""

    @property
    @abstractmethod
    def performs_scroll(self) -> bool:
        """Indicates whether this strategy scrolls down to load additional batches."""

    def attach_network_listener(
        self, page: Page, username: str, posts: dict[str, dict[str, Any]]
    ) -> None:
        """Registers the API response listener when network capture is active."""
        if not self.uses_network:
            return

        async def _on_response(response: Response) -> None:
            if "/api/post/item_list/" not in response.url or response.status != 200:
                return
            try:
                payload = await response.json()
            except Exception:
                return
            for item in payload.get("itemList") or []:
                if item.get("id"):
                    parsed = self._parser.parse_api_item(item, username)
                    posts[parsed["id"]] = parsed

        page.on("response", _on_response)

    def collect_hydration_items(
        self,
        user_detail: dict[str, Any],
        username: str,
        posts: dict[str, dict[str, Any]],
    ) -> None:
        """Extracts initial posts embedded in the SSR hydration payload."""
        if not self.uses_network:
            return
        for item in user_detail.get("itemList") or []:
            if item.get("id"):
                parsed = self._parser.parse_api_item(item, username)
                posts[parsed["id"]] = parsed

    async def collect_dom_items(
        self, page: Page, posts: dict[str, dict[str, Any]]
    ) -> None:
        """Extracts post cards from the rendered DOM when enabled."""
        if not self.uses_dom:
            return
        try:
            raw_nodes = await page.evaluate(JS_LEER_DOM, SELECTOR_POST)
        except Exception:
            return
        for raw in raw_nodes:
            parsed = self._parser.parse_dom_item(raw)
            if not parsed:
                continue
            existing = posts.get(parsed["id"])
            if existing is None:
                posts[parsed["id"]] = parsed
            elif existing["estadisticas"]["vistas"] is None:
                existing["estadisticas"]["vistas"] = parsed["estadisticas"]["vistas"]


class HybridExtractionStrategy(ExtractionStrategy):
    """Combines network API interception with DOM fallback extraction."""

    @property
    def uses_network(self) -> bool:
        return True

    @property
    def uses_dom(self) -> bool:
        return True

    @property
    def performs_scroll(self) -> bool:
        return True


class NetworkExtractionStrategy(ExtractionStrategy):
    """Captures posts exclusively from TikTok's internal network API."""

    @property
    def uses_network(self) -> bool:
        return True

    @property
    def uses_dom(self) -> bool:
        return False

    @property
    def performs_scroll(self) -> bool:
        return True


class DomExtractionStrategy(ExtractionStrategy):
    """Captures posts exclusively from rendered HTML elements."""

    @property
    def uses_network(self) -> bool:
        return False

    @property
    def uses_dom(self) -> bool:
        return True

    @property
    def performs_scroll(self) -> bool:
        return True


class QuickExtractionStrategy(ExtractionStrategy):
    """Captures only the initial batch of posts without scrolling."""

    @property
    def uses_network(self) -> bool:
        return True

    @property
    def uses_dom(self) -> bool:
        return False

    @property
    def performs_scroll(self) -> bool:
        return False


class ExtractionStrategyFactory:
    """Resolves the concrete ExtractionStrategy for a given mode name."""

    _STRATEGIES: dict[str, type[ExtractionStrategy]] = {
        "hibrido": HybridExtractionStrategy,
        "red": NetworkExtractionStrategy,
        "dom": DomExtractionStrategy,
        "rapido": QuickExtractionStrategy,
    }

    @classmethod
    def create(cls, mode: str, parser: TikTokDataParser) -> ExtractionStrategy:
        strategy_cls = cls._STRATEGIES.get(mode, HybridExtractionStrategy)
        return strategy_cls(parser)


class BrowserSessionManager:
    """Manages Playwright browser lifecycle and network resource filtering."""

    def __init__(self, playwright: Playwright, options: ScrapeOptions) -> None:
        self._playwright = playwright
        self._options = options
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> Page:
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        if self._options.headless:
            launch_args.append("--headless=new")

        ctx_kwargs = {
            "user_agent": USER_AGENTS[self._options.user_agent],
            "viewport": {"width": 1280, "height": 900},
        }

        if self._options.sesion_persistente:
            PERFIL_NAVEGADOR_DIR.mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(PERFIL_NAVEGADOR_DIR),
                headless=False,
                args=launch_args,
                **ctx_kwargs,
            )
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=launch_args,
            )
            self._context = await self._browser.new_context(**ctx_kwargs)

        page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )

        if self._options.bloquear_multimedia:
            async def _filter_resources(route) -> None:
                if route.request.resource_type in ("media", "image", "font"):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", _filter_resources)

        return page

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        for closer in (
            self._context.close if self._context else None,
            self._browser.close if self._browser else None,
        ):
            if closer:
                try:
                    await closer()
                except Exception:
                    pass


class TikTokProfileScraper:
    """Coordinates profile navigation, scrolling, and extraction strategy execution."""

    def __init__(self, parser: Optional[TikTokDataParser] = None) -> None:
        self._parser = parser or TikTokDataParser()

    async def scrape(
        self,
        username: str,
        options: ScrapeOptions,
        progress: ProgressCallback = None,
    ) -> dict[str, Any]:
        """Executes the profile scraping workflow with automatic retry support."""

        def notify(pct: int, message: str) -> None:
            if progress:
                try:
                    progress(pct, message)
                except Exception:
                    pass

        start_time = time.time()
        clean_username = username.strip().lstrip("@")
        min_timestamp = (
            datetime.strptime(options.fecha_desde, "%Y-%m-%d").timestamp()
            if options.fecha_desde
            else None
        )
        strategy = ExtractionStrategyFactory.create(options.modo, self._parser)

        async with async_playwright() as playwright:
            result: dict[str, Any] = {}
            attempt = 0
            for attempt in range(options.reintentos + 1):
                if attempt > 0:
                    wait_seconds = random.uniform(4, 9)
                    notify(
                        10,
                        f"Reintento {attempt}/{options.reintentos} en {wait_seconds:.0f} s...",
                    )
                    await asyncio.sleep(wait_seconds)

                result = await self._run_attempt(
                    playwright,
                    clean_username,
                    options,
                    strategy,
                    notify,
                    min_timestamp,
                    start_time,
                )
                if result["estado"] != "ok" or result["total_posts_extraidos"] > 0:
                    break

            result["meta"]["intentos"] = attempt + 1
            return result

    async def _run_attempt(
        self,
        playwright: Playwright,
        username: str,
        options: ScrapeOptions,
        strategy: ExtractionStrategy,
        notify: Callable[[int, str], None],
        min_timestamp: Optional[float],
        start_time: float,
    ) -> dict[str, Any]:
        url = f"https://www.tiktok.com/@{username}"
        posts: dict[str, dict[str, Any]] = {}
        profile: dict[str, Any] = {"usuario": username}

        notify(3, "Abriendo navegador...")
        async with BrowserSessionManager(playwright, options) as page:
            strategy.attach_network_listener(page, username, posts)

            notify(8, f"Cargando perfil @{username}...")
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=options.timeout_carga_s * 1000,
                )
                await page.wait_for_selector(
                    SELECTOR_HIDRATACION, state="attached", timeout=15000
                )
            except Exception:
                pass

            hydration_el = await page.query_selector(SELECTOR_HIDRATACION)
            if hydration_el:
                try:
                    hydration_data = json.loads(await hydration_el.inner_text())
                    user_detail = hydration_data.get("__DEFAULT_SCOPE__", {}).get(
                        "webapp.user-detail", {}
                    )
                    if user_detail.get("statusCode", 0) != 0:
                        return self._build_response(
                            "no_existe", username, profile, {}, options, start_time
                        )
                    profile = self._parser.parse_profile(user_detail)
                    if profile.get("privada"):
                        return self._build_response(
                            "privada", username, profile, {}, options, start_time
                        )
                    strategy.collect_hydration_items(user_detail, username, posts)
                except Exception:
                    pass

            notify(15, "Esperando lote inicial de publicaciones...")
            await self._wait_for_captcha(page, options, notify)
            loaded = await self._wait_for_initial_posts(
                page, posts, strategy.uses_network, 12000
            )
            if not loaded:
                notify(18, "Recargando página...")
                try:
                    await page.reload(
                        wait_until="domcontentloaded",
                        timeout=options.timeout_carga_s * 1000,
                    )
                    await self._wait_for_captcha(page, options, notify)
                    await self._wait_for_initial_posts(
                        page, posts, strategy.uses_network, 10000
                    )
                except Exception:
                    pass

            await strategy.collect_dom_items(page, posts)

            if not posts:
                return self._build_response(
                    "ok", username, profile, posts, options, start_time, min_timestamp
                )

            if strategy.performs_scroll and options.max_scrolls > 0:
                idle_scrolls = 0
                for index in range(options.max_scrolls):
                    previous_count = len(posts)
                    await self._perform_scroll(page, options)
                    await strategy.collect_dom_items(page, posts)

                    added = len(posts) - previous_count
                    pct = 20 + int(70 * (index + 1) / options.max_scrolls)
                    notify(
                        pct,
                        f"Scroll {index + 1}/{options.max_scrolls} · {len(posts)} posts (+{added})",
                    )

                    idle_scrolls = idle_scrolls + 1 if added == 0 else 0
                    if idle_scrolls >= options.detener_sin_nuevos:
                        notify(pct, "Sin publicaciones adicionales, finalizando scroll.")
                        break
                    if options.max_posts and len(posts) >= options.max_posts:
                        break
                    if min_timestamp and self._reached_date_threshold(posts, min_timestamp):
                        notify(pct, f"Fecha límite alcanzada ({options.fecha_desde}).")
                        break

            notify(95, "Procesando resultados...")
            return self._build_response(
                "ok", username, profile, posts, options, start_time, min_timestamp
            )

    @staticmethod
    async def _wait_for_initial_posts(
        page: Page,
        posts: dict[str, dict[str, Any]],
        uses_network: bool,
        timeout_ms: int,
    ) -> bool:
        steps = max(1, timeout_ms // 500)
        for _ in range(steps):
            if posts:
                return True
            if not uses_network:
                try:
                    if await page.query_selector(SELECTOR_POST):
                        return True
                except Exception:
                    pass
            await page.wait_for_timeout(500)
        return bool(posts)

    @staticmethod
    async def _wait_for_captcha(
        page: Page,
        options: ScrapeOptions,
        notify: Callable[[int, str], None],
    ) -> None:
        for selector in SELECTORES_CAPTCHA:
            try:
                if await page.query_selector(selector):
                    break
            except Exception:
                return
        else:
            return

        if options.headless:
            notify(16, "Captcha detectado. Activa 'Mostrar navegador' para resolverlo.")
            return

        notify(16, "Captcha detectado: resuélvelo en la ventana del navegador (90 s)...")
        for _ in range(90):
            await page.wait_for_timeout(1000)
            still_visible = False
            for selector in SELECTORES_CAPTCHA:
                try:
                    if await page.query_selector(selector):
                        still_visible = True
                        break
                except Exception:
                    pass
            if not still_visible:
                return

    @staticmethod
    async def _perform_scroll(page: Page, options: ScrapeOptions) -> None:
        try:
            if options.humanizar:
                await page.mouse.move(random.randint(500, 900), random.randint(350, 650))
                for _ in range(random.randint(3, 6)):
                    await page.mouse.wheel(0, random.randint(500, 1100))
                    await page.wait_for_timeout(random.randint(120, 380))
                if random.random() < 0.25:
                    await page.mouse.wheel(0, -random.randint(150, 400))
                    await page.wait_for_timeout(random.randint(200, 500))
            await page.evaluate(
                "window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight))"
            )
        except Exception:
            pass

        delay = options.scroll_delay_ms
        if options.humanizar:
            delay = int(delay * random.uniform(0.8, 1.4))
        await page.wait_for_timeout(delay)

    @staticmethod
    def _reached_date_threshold(
        posts: dict[str, dict[str, Any]], min_timestamp: float
    ) -> bool:
        timestamps = [
            p["timestamp"]
            for p in posts.values()
            if p.get("timestamp") and not p.get("fijado")
        ]
        return bool(timestamps) and min(timestamps) < min_timestamp

    @staticmethod
    def _build_response(
        status: str,
        username: str,
        profile: dict[str, Any],
        posts: dict[str, dict[str, Any]],
        options: ScrapeOptions,
        start_time: float,
        min_timestamp: Optional[float] = None,
    ) -> dict[str, Any]:
        items = list(posts.values())
        if min_timestamp:
            items = [
                p
                for p in items
                if not p.get("timestamp")
                or p["timestamp"] >= min_timestamp
                or p.get("fijado")
            ]
        items.sort(key=lambda p: p.get("timestamp") or 0, reverse=True)
        if options.max_posts:
            items = items[: options.max_posts]

        return {
            "estado": status,
            "usuario": username,
            "perfil": profile,
            "publica": status == "ok",
            "total_posts_extraidos": len(items),
            "posts": items,
            "meta": {
                "fecha_scrape": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "duracion_s": round(time.time() - start_time, 1),
                "opciones": asdict(options),
                "posts_api": sum(1 for p in items if p.get("fuente") == "api"),
                "posts_dom": sum(1 for p in items if p.get("fuente") == "dom"),
            },
        }


async def scrape_tiktok_profile(
    username: str,
    opciones: ScrapeOptions | dict[str, Any] | int | None = None,
    progreso: ProgressCallback = None,
) -> dict[str, Any]:
    """Facade function that executes TikTokProfileScraper with normalized options."""
    if isinstance(opciones, int):
        parsed_options = ScrapeOptions(max_scrolls=opciones)
    elif isinstance(opciones, ScrapeOptions):
        parsed_options = opciones
    else:
        parsed_options = ScrapeOptions.desde_dict(opciones)

    scraper = TikTokProfileScraper()
    return await scraper.scrape(username, parsed_options, progreso)

