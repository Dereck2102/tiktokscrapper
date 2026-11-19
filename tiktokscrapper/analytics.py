"""Analytical engine for TikTok profile metrics, distributions, and rule-based insights."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from datetime import datetime
from statistics import median
from typing import Any, Callable, Iterable, Optional

DIAS: list[str] = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]

RANGOS_DURACION: list[tuple[int, int, str]] = [
    (0, 15, "0-15 s"),
    (15, 30, "15-30 s"),
    (30, 60, "30-60 s"),
    (60, 180, "1-3 min"),
    (180, 10**9, "+3 min"),
]


class MetricCalculator:
    """Statistical and formatting helper methods for analytical aggregations."""

    @staticmethod
    def mean(values: Iterable[Optional[float | int]]) -> float:
        valid = [float(x) for x in values if x is not None]
        return sum(valid) / len(valid) if valid else 0.0

    @staticmethod
    def median_value(values: Iterable[Optional[float | int]]) -> float:
        valid = [float(x) for x in values if x is not None]
        return float(median(valid)) if valid else 0.0

    @staticmethod
    def format_compact(value: Optional[float | int]) -> str:
        if value is None:
            return "—"
        num = float(value)
        for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(num) >= threshold:
                return f"{num / threshold:.1f}{suffix}"
        return f"{num:.0f}"


class PostEnricher:
    """Computes derived engagement and temporal indicators for individual posts."""

    @staticmethod
    def compute_interactions(post: dict[str, Any]) -> Optional[int]:
        stats = post.get("estadisticas", {})
        fields = [
            stats.get("likes"),
            stats.get("comentarios"),
            stats.get("compartidos"),
            stats.get("guardados"),
        ]
        if all(field is None for field in fields):
            return None
        return sum(int(field or 0) for field in fields)

    @classmethod
    def enrich_all(
        cls,
        posts: list[dict[str, Any]],
        followers: Optional[int] = None,
        velocities: Optional[dict[str, dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        velocity_map = velocities or {}
        enriched: list[dict[str, Any]] = []
        for post in posts:
            item = dict(post)
            views = post.get("estadisticas", {}).get("vistas")
            interactions = cls.compute_interactions(post)
            item["interacciones"] = interactions
            item["er"] = (
                round(interactions / views * 100, 2)
                if interactions is not None and views
                else None
            )
            item["er_seguidores"] = (
                round(interactions / followers * 100, 2)
                if interactions is not None and followers
                else None
            )
            if post.get("timestamp"):
                dt = datetime.fromtimestamp(post["timestamp"])
                item["dia_semana"] = DIAS[dt.weekday()]
                item["hora"] = dt.hour
                item["dias_publicado"] = max((datetime.now() - dt).days, 0)
                item["vistas_por_dia"] = (
                    round(views / max(item["dias_publicado"], 1)) if views else None
                )
            else:
                item["dia_semana"] = None
                item["hora"] = None
                item["dias_publicado"] = None
                item["vistas_por_dia"] = None
            item["velocidad"] = velocity_map.get(post["id"])
            enriched.append(item)
        return enriched


class InsightRule(ABC):
    """Contract for analytical rules that evaluate dashboard metrics and emit insights."""

    @abstractmethod
    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        """Evaluates the dashboard state and returns zero or more insight entries."""


class SampleSizeRule(InsightRule):
    """Checks whether the analyzed post sample is statistically sufficient."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        count = dashboard["kpis"]["posts_analizados"]
        if count < 10:
            return [
                {
                    "tipo": "aviso",
                    "titulo": "Muestra reducida",
                    "texto": f"Se analizaron {count} publicaciones. Incrementa el número de scrolls para mayor representatividad.",
                }
            ]
        return []


class EngagementRateRule(InsightRule):
    """Classifies the account's average engagement rate per view."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        kpis = dashboard["kpis"]
        if not kpis["posts_con_datos_completos"]:
            return []
        er = kpis.get("er_promedio") or 0.0
        if er >= 10:
            level, kind = "alto", "positivo"
        elif er >= 5:
            level, kind = "sólido", "positivo"
        elif er >= 2.5:
            level, kind = "estándar", "neutral"
        else:
            level, kind = "bajo", "negativo"
        return [
            {
                "tipo": kind,
                "titulo": f"Engagement {level}: {er}%",
                "texto": "Proporción de interacciones totales (likes, comentarios, compartidos y guardados) sobre vistas.",
            }
        ]


class ReachRule(InsightRule):
    """Evaluates average post views relative to the follower base."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        reach = dashboard["kpis"].get("alcance_vs_seguidores")
        if reach is None:
            return []
        if reach >= 100:
            return [
                {
                    "tipo": "positivo",
                    "titulo": f"Alcance superior a la base ({reach}%)",
                    "texto": "Las publicaciones superan en promedio el total de seguidores de la cuenta.",
                }
            ]
        if reach < 10:
            return [
                {
                    "tipo": "negativo",
                    "titulo": f"Alcance reducido frente a seguidores ({reach}%)",
                    "texto": "Las publicaciones alcanzan en promedio menos del 10% de la audiencia registrada.",
                }
            ]
        return []


class BestDayRule(InsightRule):
    """Identifies the day of the week with the highest average views."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        days = [d for d in dashboard["dias"] if d["posts"] >= 2]
        if len(days) < 2:
            return []
        best = max(days, key=lambda x: x["vistas_promedio"])
        worst = min(days, key=lambda x: x["vistas_promedio"])
        return [
            {
                "tipo": "positivo",
                "titulo": f"Día de mayor rendimiento: {best['dia']}",
                "texto": (
                    f"Promedio de {MetricCalculator.format_compact(best['vistas_promedio'])} vistas "
                    f"frente a {MetricCalculator.format_compact(worst['vistas_promedio'])} los {worst['dia']}."
                ),
            }
        ]


class BestHourRule(InsightRule):
    """Identifies the publishing hour with the highest average views."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        hours = [h for h in dashboard["horas"] if h["posts"] >= 2]
        if len(hours) < 2:
            return []
        best = max(hours, key=lambda x: x["vistas_promedio"])
        next_hour = (best["hora"] + 1) % 24
        return [
            {
                "tipo": "positivo",
                "titulo": f"Franja horaria destacada: {best['hora']:02d}:00 - {next_hour:02d}:00",
                "texto": f"Las publicaciones en este horario promedian {MetricCalculator.format_compact(best['vistas_promedio'])} vistas.",
            }
        ]


class OptimalDurationRule(InsightRule):
    """Identifies the video duration bucket with the highest average views."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        buckets = [b for b in dashboard["duraciones"] if b["posts"] >= 2]
        if len(buckets) < 2:
            return []
        best = max(buckets, key=lambda x: x["vistas_promedio"])
        return [
            {
                "tipo": "positivo",
                "titulo": f"Duración con mejor respuesta: {best['rango']}",
                "texto": f"Registra un promedio de {MetricCalculator.format_compact(best['vistas_promedio'])} vistas ({best['posts']} publicaciones).",
            }
        ]


class HashtagPerformanceRule(InsightRule):
    """Highlights top-performing and underperforming hashtags relative to median views."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        tags = [h for h in dashboard["hashtags"] if h["usos"] >= 2 and h["indice"]]
        if not tags:
            return []
        results: list[dict[str, str]] = []
        best = max(tags, key=lambda h: h["indice"])
        if best["indice"] > 1:
            results.append(
                {
                    "tipo": "positivo",
                    "titulo": f"Hashtag de alto rendimiento: #{best['tag']}",
                    "texto": f"Rinde {best['indice']}x la mediana de vistas de la cuenta en {best['usos']} publicaciones.",
                }
            )
        worst = min(tags, key=lambda h: h["indice"])
        if worst["indice"] < 0.7 and worst["tag"] != best["tag"]:
            results.append(
                {
                    "tipo": "negativo",
                    "titulo": f"Hashtag por debajo de la mediana: #{worst['tag']}",
                    "texto": f"Rinde {worst['indice']}x la mediana de vistas en {worst['usos']} publicaciones.",
                }
            )
        return results


class CadenceRule(InsightRule):
    """Evaluates weekly publishing frequency."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        kpis = dashboard["kpis"]
        freq = kpis.get("frecuencia_semanal")
        if freq is None:
            return []
        if freq < 2:
            return [
                {
                    "tipo": "neutral",
                    "titulo": f"Frecuencia de publicación: {freq} posts/semana",
                    "texto": f"Intervalo medio de {kpis['dias_entre_posts']} días entre publicaciones.",
                }
            ]
        return [
            {
                "tipo": "positivo",
                "titulo": f"Cadencia activa: {freq} posts/semana",
                "texto": f"Intervalo medio de {kpis['dias_entre_posts']} días entre publicaciones.",
            }
        ]


class ViralPostsRule(InsightRule):
    """Detects outlier posts exceeding three times the account's median views."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        virals = dashboard["virales"]
        if not virals:
            return []
        return [
            {
                "tipo": "positivo",
                "titulo": f"{len(virals)} publicación(es) atípica(s) de alto alcance",
                "texto": "Superan en al menos 3x la mediana de vistas de la muestra analizada.",
            }
        ]


class AudioSourceRule(InsightRule):
    """Compares performance between original audio and third-party sounds."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        by_type = {x["tipo"]: x for x in dashboard["musica"]}
        if "Audio original" not in by_type or "Audio de terceros" not in by_type:
            return []
        orig = by_type["Audio original"]["vistas_promedio"]
        third = by_type["Audio de terceros"]["vistas_promedio"]
        if not orig or not third:
            return []
        leader = "audio original" if orig > third else "audio de terceros"
        return [
            {
                "tipo": "neutral",
                "titulo": f"Mayor alcance con {leader}",
                "texto": (
                    f"Audio original: {MetricCalculator.format_compact(orig)} vistas prom. · "
                    f"Terceros: {MetricCalculator.format_compact(third)} vistas prom."
                ),
            }
        ]


class ContentTypeRule(InsightRule):
    """Compares performance between video posts and photo carousels."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        by_type = {x["tipo"]: x for x in dashboard["tipos"]}
        if "foto" in by_type and "video" in by_type and by_type["foto"]["posts"] >= 2:
            return [
                {
                    "tipo": "neutral",
                    "titulo": "Comparativa por formato",
                    "texto": (
                        f"Fotos: {MetricCalculator.format_compact(by_type['foto']['vistas_promedio'])} vistas prom. · "
                        f"Videos: {MetricCalculator.format_compact(by_type['video']['vistas_promedio'])} vistas prom."
                    ),
                }
            ]
        return []


class HistoricalGrowthRule(InsightRule):
    """Summarizes follower variation across stored snapshots."""

    def evaluate(self, dashboard: dict[str, Any]) -> list[dict[str, str]]:
        growth = dashboard.get("crecimiento")
        if not growth:
            return []
        delta = growth["seguidores"]
        kind = "positivo" if delta >= 0 else "negativo"
        sign = "+" if delta >= 0 else ""
        return [
            {
                "tipo": kind,
                "titulo": f"Variación de seguidores: {sign}{MetricCalculator.format_compact(delta)}",
                "texto": (
                    f"Periodo {growth['desde']} a {growth['hasta']} "
                    f"({sign}{MetricCalculator.format_compact(growth['likes'])} likes, +{growth['videos']} videos)."
                ),
            }
        ]


class DashboardBuilder:
    """Builds the analytical dashboard model from raw scrape results and historical records."""

    DEFAULT_RULES: tuple[InsightRule, ...] = (
        SampleSizeRule(),
        EngagementRateRule(),
        ReachRule(),
        BestDayRule(),
        BestHourRule(),
        OptimalDurationRule(),
        HashtagPerformanceRule(),
        CadenceRule(),
        ViralPostsRule(),
        AudioSourceRule(),
        ContentTypeRule(),
        HistoricalGrowthRule(),
    )

    def __init__(
        self,
        enricher: Optional[PostEnricher] = None,
        rules: Optional[Iterable[InsightRule]] = None,
    ) -> None:
        self._enricher = enricher or PostEnricher()
        self._rules = tuple(rules) if rules is not None else self.DEFAULT_RULES

    @staticmethod
    def _group_by(
        posts: list[dict[str, Any]],
        key_fn: Callable[[dict[str, Any]], Any],
        metric: str = "vistas",
    ) -> dict[Any, list[Optional[float | int]]]:
        groups: dict[Any, list[Optional[float | int]]] = defaultdict(list)
        for post in posts:
            key = key_fn(post)
            if key is None:
                continue
            value = (
                post.get("estadisticas", {}).get(metric)
                if metric != "er"
                else post.get("er")
            )
            groups[key].append(value)
        return groups

    @staticmethod
    def _duration_bucket(post: dict[str, Any]) -> Optional[str]:
        duration = post.get("duracion")
        if not duration:
            return None
        for low, high, label in RANGOS_DURACION:
            if low <= duration < high:
                return label
        return None

    @staticmethod
    def _summarize_post(post: dict[str, Any], median_views: float) -> dict[str, Any]:
        views = post.get("estadisticas", {}).get("vistas")
        return {
            "id": post["id"],
            "url": post["url"],
            "fecha": post.get("fecha"),
            "desc": (post.get("descripcion") or "")[:120],
            "vistas": views,
            "likes": post.get("estadisticas", {}).get("likes"),
            "comentarios": post.get("estadisticas", {}).get("comentarios"),
            "er": post.get("er"),
            "portada": post.get("portada"),
            "multiplicador": (
                round(views / median_views, 1) if median_views and views else None
            ),
        }

    def build(
        self,
        result: dict[str, Any],
        history: Optional[list[dict[str, Any]]] = None,
        velocities: Optional[dict[str, dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Constructs the complete dashboard dictionary for a scrape result."""
        profile = result.get("perfil") or {}
        followers = profile.get("seguidores")
        posts = self._enricher.enrich_all(
            result.get("posts", []), followers, velocities
        )
        with_views = [
            p for p in posts if p.get("estadisticas", {}).get("vistas") is not None
        ]
        with_api = [p for p in posts if p.get("interacciones") is not None]
        dated = sorted(
            [p for p in posts if p.get("timestamp")], key=lambda p: p["timestamp"]
        )
        unpinned_dated = [p for p in dated if not p.get("fijado")]

        views_list = [p["estadisticas"]["vistas"] for p in with_views]
        median_views = MetricCalculator.median_value(views_list)

        weekly_freq: Optional[float] = None
        days_between: Optional[float] = None
        if len(unpinned_dated) >= 2:
            span_days = (
                unpinned_dated[-1]["timestamp"] - unpinned_dated[0]["timestamp"]
            ) / 86400
            if span_days > 0:
                weekly_freq = round((len(unpinned_dated) - 1) / span_days * 7, 2)
                days_between = round(span_days / (len(unpinned_dated) - 1), 2)

        avg_interactions = MetricCalculator.mean([p["interacciones"] for p in with_api])
        kpis = {
            "posts_analizados": len(posts),
            "posts_con_datos_completos": len(with_api),
            "vistas_totales": int(sum(views_list)),
            "vistas_promedio": round(MetricCalculator.mean(views_list)),
            "vistas_mediana": round(median_views),
            "likes_promedio": round(
                MetricCalculator.mean([p["estadisticas"].get("likes") for p in with_api])
            ),
            "comentarios_promedio": round(
                MetricCalculator.mean(
                    [p["estadisticas"].get("comentarios") for p in with_api]
                )
            ),
            "compartidos_promedio": round(
                MetricCalculator.mean(
                    [p["estadisticas"].get("compartidos") for p in with_api]
                )
            ),
            "guardados_promedio": round(
                MetricCalculator.mean(
                    [p["estadisticas"].get("guardados") for p in with_api]
                )
            ),
            "interacciones_promedio": round(avg_interactions),
            "er_promedio": round(
                MetricCalculator.mean([p["er"] for p in with_api]), 2
            ),
            "er_seguidores": (
                round(avg_interactions / followers * 100, 2)
                if followers and with_api
                else None
            ),
            "alcance_vs_seguidores": (
                round(MetricCalculator.mean(views_list) / followers * 100, 1)
                if followers and views_list
                else None
            ),
            "frecuencia_semanal": weekly_freq,
            "dias_entre_posts": days_between,
            "duracion_promedio": round(
                MetricCalculator.mean(
                    [p.get("duracion") for p in posts if p.get("duracion")]
                ),
                1,
            ),
        }

        timeline = [
            {
                "fecha": p["fecha"],
                "id": p["id"],
                "url": p["url"],
                "vistas": p["estadisticas"].get("vistas"),
                "likes": p["estadisticas"].get("likes"),
                "er": p.get("er"),
                "desc": (p.get("descripcion") or "")[:80],
            }
            for p in dated
        ]

        by_day = self._group_by(with_views, lambda p: p.get("dia_semana"))
        days = [
            {
                "dia": day,
                "posts": len(by_day.get(day, [])),
                "vistas_promedio": round(MetricCalculator.mean(by_day.get(day, []))),
            }
            for day in DIAS
        ]

        by_hour = self._group_by(with_views, lambda p: p.get("hora"))
        hours = [
            {
                "hora": hour,
                "posts": len(by_hour.get(hour, [])),
                "vistas_promedio": round(MetricCalculator.mean(by_hour.get(hour, []))),
            }
            for hour in range(24)
        ]

        by_dur = self._group_by(with_views, self._duration_bucket)
        by_dur_er = self._group_by(with_api, self._duration_bucket, "er")
        durations = [
            {
                "rango": label,
                "posts": len(by_dur.get(label, [])),
                "vistas_promedio": round(MetricCalculator.mean(by_dur.get(label, []))),
                "er_promedio": round(
                    MetricCalculator.mean(by_dur_er.get(label, [])), 2
                ),
            }
            for _, _, label in RANGOS_DURACION
        ]

        tag_counts: Counter[str] = Counter()
        tag_views: dict[str, list[Optional[int]]] = defaultdict(list)
        tag_er: dict[str, list[Optional[float]]] = defaultdict(list)
        for post in posts:
            for tag in post.get("hashtags") or []:
                tag_counts[tag] += 1
                tag_views[tag].append(post["estadisticas"].get("vistas"))
                tag_er[tag].append(post.get("er"))

        hashtags = [
            {
                "tag": tag,
                "usos": count,
                "vistas_promedio": round(MetricCalculator.mean(tag_views[tag])),
                "er_promedio": round(MetricCalculator.mean(tag_er[tag]), 2),
                "indice": (
                    round(MetricCalculator.mean(tag_views[tag]) / median_views, 2)
                    if median_views
                    else None
                ),
            }
            for tag, count in tag_counts.most_common(30)
        ]

        by_type = self._group_by(with_views, lambda p: p.get("tipo"))
        types = [
            {
                "tipo": k,
                "posts": len(v),
                "vistas_promedio": round(MetricCalculator.mean(v)),
            }
            for k, v in by_type.items()
        ]

        by_music = self._group_by(
            with_views,
            lambda p: (
                None
                if (p.get("musica") or {}).get("original") is None
                else (
                    "Audio original"
                    if p["musica"]["original"]
                    else "Audio de terceros"
                )
            ),
        )
        music = [
            {
                "tipo": k,
                "posts": len(v),
                "vistas_promedio": round(MetricCalculator.mean(v)),
            }
            for k, v in by_music.items()
        ]

        top_sounds = Counter(
            (p.get("musica") or {}).get("titulo")
            for p in posts
            if (p.get("musica") or {}).get("titulo")
            and not p["musica"].get("original")
        ).most_common(10)

        top_views = [
            self._summarize_post(p, median_views)
            for p in sorted(
                with_views,
                key=lambda p: p["estadisticas"]["vistas"],
                reverse=True,
            )[:5]
        ]
        top_er = [
            self._summarize_post(p, median_views)
            for p in sorted(
                [p for p in with_api if p.get("er") is not None],
                key=lambda p: p["er"],
                reverse=True,
            )[:5]
        ]
        lowest_views = [
            self._summarize_post(p, median_views)
            for p in sorted(with_views, key=lambda p: p["estadisticas"]["vistas"])[:5]
        ]
        viral_posts = [
            self._summarize_post(p, median_views)
            for p in with_views
            if median_views and p["estadisticas"]["vistas"] >= 3 * median_views
        ]
        with_velocity = [p for p in posts if p.get("velocidad")]
        trending = [
            dict(self._summarize_post(p, median_views), **p["velocidad"])
            for p in sorted(
                with_velocity,
                key=lambda p: p["velocidad"]["vistas_por_hora"],
                reverse=True,
            )[:5]
        ]

        growth = None
        history_list = history or []
        if len(history_list) >= 2:
            first, last = history_list[0], history_list[-1]
            growth = {
                "desde": first["fecha"],
                "hasta": last["fecha"],
                "seguidores": (last.get("seguidores") or 0)
                - (first.get("seguidores") or 0),
                "likes": (last.get("likes_totales") or 0)
                - (first.get("likes_totales") or 0),
                "videos": (last.get("videos") or 0) - (first.get("videos") or 0),
            }

        dashboard: dict[str, Any] = {
            "perfil": profile,
            "meta": result.get("meta", {}),
            "kpis": kpis,
            "linea_tiempo": timeline,
            "dias": days,
            "horas": hours,
            "duraciones": durations,
            "hashtags": hashtags,
            "tipos": types,
            "musica": music,
            "sonidos": [{"titulo": title, "usos": count} for title, count in top_sounds],
            "top_vistas": top_views,
            "top_er": top_er,
            "peores": lowest_views,
            "virales": viral_posts,
            "tendencia": trending,
            "historial": history_list,
            "crecimiento": growth,
            "posts": posts,
        }

        insights: list[dict[str, str]] = []
        for rule in self._rules:
            insights.extend(rule.evaluate(dashboard))
        dashboard["insights"] = insights
        return dashboard


class AccountBenchmarker:
    """Computes relative performance ratios across multiple tracked accounts."""

    @staticmethod
    def compare(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for account in accounts:
            followers = account.get("seguidores") or 0
            output.append(
                dict(
                    account,
                    likes_por_seguidor=(
                        round((account.get("likes_totales") or 0) / followers, 1)
                        if followers
                        else None
                    ),
                    alcance_pct=(
                        round((account.get("vistas_promedio") or 0) / followers * 100, 1)
                        if followers
                        else None
                    ),
                )
            )
        return output


default_dashboard_builder = DashboardBuilder()


def enriquecer_posts(
    posts: list[dict[str, Any]],
    seguidores: Optional[int] = None,
    velocidad: Optional[dict[str, dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Enriches a post list using PostEnricher."""
    return PostEnricher.enrich_all(posts, seguidores, velocidad)


def construir_dashboard(
    resultado: dict[str, Any],
    historial: Optional[list[dict[str, Any]]] = None,
    velocidad: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Builds a dashboard model using the default DashboardBuilder."""
    return default_dashboard_builder.build(resultado, historial, velocidad)


def comparar_cuentas(cuentas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalizes account comparison metrics using AccountBenchmarker."""
    return AccountBenchmarker.compare(cuentas)

