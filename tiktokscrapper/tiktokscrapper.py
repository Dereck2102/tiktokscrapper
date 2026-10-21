import asyncio
import json
import os
from pathlib import Path
from flask import Flask, request, render_template, Response
from scraper import scrape_tiktok_profile

app = Flask(__name__)
ULTIMO_RESULTADO = {}


@app.route("/", methods=["GET", "POST"])
def index():
    datos = None
    mensaje = "Ingresa un usuario público de TikTok y presiona 'Extraer Posts'."
    es_error = False
    username = ""
    scrolls = 3

    if request.method == "POST":
        username = request.form.get("username", "").strip().lstrip("@")
        scrolls = int(request.form.get("scrolls", 3))

        if username:
            datos = asyncio.run(scrape_tiktok_profile(username, scrolls))

            if datos["estado"] == "no_existe":
                mensaje = f"La cuenta @{username} no existe o no está disponible."
                es_error = True
            elif datos["estado"] == "privada":
                mensaje = f"La cuenta @{username} es PRIVADA. No se pueden ver sus publicaciones."
                es_error = True
            else:
                ULTIMO_RESULTADO[username] = datos
                carpeta_documentos = Path.home() / "Documents"
                carpeta_documentos.mkdir(parents=True, exist_ok=True)
                archivo_salida = carpeta_documentos / f"tiktok_{username}.json"
                with open(archivo_salida, "w", encoding="utf-8") as f:
                    json.dump(datos, f, ensure_ascii=False, indent=4)

                mensaje = f"¡Listo! {datos['total_posts_extraidos']} posts extraídos de @{username}. Guardado en {archivo_salida}."

    return render_template(
        "index.html",
        datos=datos,
        mensaje=mensaje,
        es_error=es_error,
        username=username,
        scrolls=scrolls
    )


@app.route("/descargar/<username>")
def descargar_json(username):
    datos = ULTIMO_RESULTADO.get(username)
    if not datos:
        return "No hay datos recientes para este usuario.", 404
    contenido = json.dumps(datos, ensure_ascii=False, indent=4)
    return Response(
        contenido,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=tiktok_{username}.json"}
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)     