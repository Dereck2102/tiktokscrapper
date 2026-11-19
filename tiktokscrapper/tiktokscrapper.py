"""Flask web application entrypoint and HTTP controller layer."""

from __future__ import annotations

import asyncio
import itertools
import os
import queue
import re
import threading
import traceback
from datetime import datetime
from typing import Any, Callable, Optional

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from analytics import AccountBenchmarker, DashboardBuilder, default_dashboard_builder
from exporters import ExporterRegistry, XLSX_DISPONIBLE, default_exporter_registry
from scraper import MODOS, USER_AGENTS, ScrapeOptions, scrape_tiktok_profile
from storage import ScraperRepository, default_repository


class UsernameParser:
    """Extracts and normalizes TikTok usernames from text or profile URLs."""

    @staticmethod
    def parse(raw_text: str) -> list[str]:
        usernames: list[str] = []
        for token in re.split(r"[\s,;]+", raw_text or ""):
            cleaned = token.strip()
            url_match = re.search(r"tiktok\.com/@([\w.\-]+)", cleaned)
            if url_match:
                cleaned = url_match.group(1)
            cleaned = cleaned.lstrip("@")
            if re.fullmatch(r"[\w.\-]{1,40}", cleaned) and cleaned.lower() not in usernames:
                usernames.append(cleaned.lower())
        return usernames


class ScrapeJobQueue:
    """Thread-safe sequential background queue for profile scraping tasks."""

    def __init__(
        self,
        repository: ScraperRepository,
        scraper_fn: Callable[..., Any] = scrape_tiktok_profile,
    ) -> None:
        self._repository = repository
        self._scraper_fn = scraper_fn
        self._jobs: dict[int, dict[str, Any]] = {}
        self._queue: queue.Queue[int] = queue.Queue()
        self._counter = itertools.count(1)
        self._lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._process_loop, daemon=True, name="scraper-worker"
        )
        self._worker.start()

    def enqueue(self, usernames: list[str], options: ScrapeOptions) -> list[int]:
        """Enqueues scraping jobs for the given usernames and returns their IDs."""
        job_ids: list[int] = []
        with self._lock:
            for username in usernames:
                job_id = next(self._counter)
                self._jobs[job_id] = {
                    "id": job_id,
                    "username": username,
                    "opciones": options,
                    "estado": "en_cola",
                    "progreso": 0,
                    "mensaje": "En cola...",
                    "scrape_id": None,
                    "total": None,
                    "creado": datetime.now().strftime("%H:%M:%S"),
                }
                self._queue.put(job_id)
                job_ids.append(job_id)
        return job_ids

    def list_recent(self, limit: int = 30) -> list[dict[str, Any]]:
        """Returns serialized representations of the most recent jobs."""
        recent = sorted(self._jobs.values(), key=lambda j: j["id"], reverse=True)[:limit]
        return [self._serialize(job) for job in recent]

    def get_job(self, job_id: int) -> Optional[dict[str, Any]]:
        """Returns the serialized representation of a single job by ID."""
        job = self._jobs.get(job_id)
        return self._serialize(job) if job else None

    def clear_finished(self) -> None:
        """Removes completed and failed jobs from the in-memory registry."""
        with self._lock:
            finished = [
                jid
                for jid, data in self._jobs.items()
                if data["estado"] in ("completado", "error")
            ]
            for jid in finished:
                self._jobs.pop(jid, None)

    @staticmethod
    def _serialize(job: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in job.items() if k != "opciones"} | {
            "modo": job["opciones"].modo
        }

    def _process_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._execute_job(job_id)
            finally:
                self._queue.task_done()

    def _execute_job(self, job_id: int) -> None:
        job = self._jobs[job_id]
        job.update(estado="ejecutando", inicio=datetime.now().strftime("%H:%M:%S"))

        def on_progress(pct: int, msg: str) -> None:
            job["progreso"] = pct
            job["mensaje"] = msg

        try:
            result = asyncio.run(
                self._scraper_fn(job["username"], job["opciones"], on_progress)
            )
            if result["estado"] == "ok":
                job["scrape_id"] = self._repository.save_scrape(result)
                job["total"] = result["total_posts_extraidos"]
                job.update(
                    estado="completado",
                    progreso=100,
                    mensaje=(
                        f"{result['total_posts_extraidos']} posts en "
                        f"{result['meta']['duracion_s']} s"
                    ),
                )
            elif result["estado"] == "privada":
                job.update(estado="error", progreso=100, mensaje="La cuenta es privada")
            else:
                job.update(
                    estado="error",
                    progreso=100,
                    mensaje="La cuenta no existe o no está disponible",
                )
        except Exception as exc:
            traceback.print_exc()
            job.update(estado="error", progreso=100, mensaje=f"Error: {exc}")
        job["fin"] = datetime.now().strftime("%H:%M:%S")


def create_app(
    repository: ScraperRepository = default_repository,
    dashboard_builder: DashboardBuilder = default_dashboard_builder,
    exporter_registry: ExporterRegistry = default_exporter_registry,
) -> Flask:
    """Application factory configuring routes and dependencies."""
    flask_app = Flask(__name__)
    repository.initialize()
    job_queue = ScrapeJobQueue(repository)

    def _file_response(content: bytes, filename: str, mime_type: str) -> Response:
        return Response(
            content,
            mimetype=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @flask_app.route("/")
    def index():
        accounts = AccountBenchmarker.compare(repository.list_accounts())
        return render_template(
            "index.html",
            cuentas=accounts,
            modos=MODOS,
            user_agents=list(USER_AGENTS.keys()),
            defaults=ScrapeOptions(),
            xlsx=XLSX_DISPONIBLE,
        )

    @flask_app.route("/dashboard/<username>")
    def dashboard(username: str):
        normalized = username.lower()
        scrape_id = request.args.get("scrape", type=int) or repository.get_latest_scrape_id(
            normalized
        )
        result = repository.get_scrape_result(scrape_id) if scrape_id else None
        if not result:
            return redirect(url_for("index"))
        dash = dashboard_builder.build(
            result,
            history=repository.get_profile_history(normalized),
            velocities=repository.get_post_velocity(normalized),
        )
        return render_template(
            "dashboard.html",
            dash=dash,
            username=normalized,
            scrape_id=scrape_id,
            scrapes=repository.list_scrapes(normalized),
            xlsx=XLSX_DISPONIBLE,
        )

    @flask_app.post("/api/scrape")
    def api_scrape():
        payload = request.get_json(silent=True) or request.form.to_dict()
        usernames = UsernameParser.parse(payload.get("usernames", ""))
        if not usernames:
            return jsonify(error="Ingresa al menos un usuario válido"), 400
        options = ScrapeOptions.desde_dict(payload)
        ids = job_queue.enqueue(usernames, options)
        return jsonify(trabajos=ids)

    @flask_app.get("/api/jobs")
    def api_jobs():
        return jsonify(job_queue.list_recent())

    @flask_app.get("/api/jobs/<int:job_id>")
    def api_job(job_id: int):
        job = job_queue.get_job(job_id)
        return jsonify(job) if job else (jsonify(error="no existe"), 404)

    @flask_app.post("/api/jobs/limpiar")
    def api_jobs_limpiar():
        job_queue.clear_finished()
        return jsonify(ok=True)

    @flask_app.post("/api/cuentas/<username>/eliminar")
    def api_eliminar(username: str):
        repository.delete_account(username)
        return jsonify(ok=True)

    @flask_app.get("/exportar/<int:scrape_id>.<fmt>")
    def exportar_scrape(scrape_id: int, fmt: str):
        result = repository.get_scrape_result(scrape_id)
        if not result:
            abort(404)
        exporter = exporter_registry.get_scrape_exporter(fmt)
        if not exporter:
            abort(404)
        if fmt.lower() == "xlsx" and not XLSX_DISPONIBLE:
            return "openpyxl no está instalado.", 501

        username = result["usuario"]
        timestamp_str = (
            (result.get("meta", {}).get("fecha_scrape") or "")
            .replace(":", "")
            .replace(" ", "_")
        )
        filename = f"tiktok_{username}_{timestamp_str}.{fmt.lower()}"
        dash = (
            {}
            if fmt.lower() == "json"
            else dashboard_builder.build(
                result,
                repository.get_profile_history(username),
                repository.get_post_velocity(username),
            )
        )
        return _file_response(
            exporter.export_scrape(result, dash), filename, exporter.mime_type
        )

    @flask_app.get("/exportar/dataset.<fmt>")
    def exportar_dataset(fmt: str):
        username = request.args.get("usuario")
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        base_name = f"dataset_{username or 'tiktok'}_{stamp}"

        if fmt.lower() == "db":
            return send_file(
                repository.db_path,
                as_attachment=True,
                download_name=f"tiktok_{stamp}.db",
            )

        exporter = exporter_registry.get_dataset_exporter(fmt)
        if not exporter:
            abort(404)
        if fmt.lower() == "xlsx" and not XLSX_DISPONIBLE:
            return "openpyxl no está instalado.", 501

        posts = repository.get_posts_dataset(username)
        profiles = repository.get_profiles_dataset() if fmt.lower() != "csv" else []
        return _file_response(
            exporter.export_dataset(posts, profiles),
            f"{base_name}.{fmt.lower()}",
            exporter.mime_type,
        )

    return flask_app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
    app.run(host="0.0.0.0", port=port, debug=False)