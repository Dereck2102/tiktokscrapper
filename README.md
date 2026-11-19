# TikTok Profile Scraper y Dashboard Local

Este proyecto es una herramienta web local hecha en Python para extraer publicaciones de perfiles públicos de TikTok, guardar un historial de los datos y ver estadísticas de cada cuenta en un panel (dashboard) sin usar APIs externas ni servicios de pago.

## Qué hace el proyecto

- **Extrae publicaciones de cuentas públicas**: obtiene vistas, likes, comentarios, compartidos, guardados, duración del video, fecha, descripción, hashtags y audio.
- **Varios modos de extracción**: permite elegir entre modo híbrido (red + HTML), solo red, solo lectura visual de la página (DOM) o modo rápido sin hacer scroll.
- **Cola de trabajo**: puedes poner uno o varios usuarios a la vez y ver cómo avanza el proceso en pantalla sin que la página se congele.
- **Base de datos local (Big File)**: todo lo que se extrae se guarda automáticamente en una base de datos SQLite local. Si vuelves a analizar la misma cuenta días después, el programa actualiza los datos y compara cómo creció.
- **Dashboard por cuenta**: muestra gráficos con las vistas en el tiempo, mejores días y horas de publicación, duración que mejor funciona, hashtags más usados y el porcentaje de interacción (Engagement Rate).
- **Exportación**: permite descargar los resultados de una cuenta o de todas las cuentas juntas en formato CSV, Excel (.xlsx), JSON o directamente el archivo SQLite.

## Herramientas utilizadas

- **Python 3.11**
- **Playwright**: abre un navegador Chromium real para navegar por el perfil de TikTok y capturar los datos tal como los recibe la página web.
- **Flask**: levanta el servidor web local para usar la herramienta desde el navegador.
- **SQLite**: guarda los perfiles, publicaciones e historial en un archivo local sin necesidad de instalar motores de bases de datos aparte.
- **OpenPyXL**: genera los archivos de Excel con varias hojas.
- **HTML, CSS y JavaScript (Chart.js)**: para la interfaz y las gráficas del panel.

## Cómo ejecutarlo

1. Clonar o descargar el repositorio y abrir una terminal dentro de la carpeta `tiktokscrapper`:

```bash
cd tiktokscrapper
```

2. Instalar las librerías necesarias:

```bash
pip install -r requirements.txt
```

3. Instalar el navegador Chromium de Playwright (solo la primera vez):

```bash
playwright install chromium
```

4. Iniciar la aplicación:

```bash
python tiktokscrapper.py
```

5. Abrir en el navegador la dirección:

```text
http://127.0.0.1:5000
```

## Equipo donde se desarrolló y probó

Actualmente el proyecto corre de forma local en un portátil con las siguientes características:

- **Equipo**: Lenovo (modelo 81BD)
- **Procesador**: Intel Core i5-8250U a 1.60 GHz (4 núcleos físicos / 8 hilos lógicos)
- **Memoria RAM**: 16 GB
- **Gráficos**: Intel UHD Graphics 620 (integrados)
- **Sistema Operativo**: Windows 11 Enterprise de 64 bits
- **Entorno**: Python 3.11.9

## Créditos

El desarrollo, la idea del proyecto, las pruebas y la definición de lo que debía hacer la herramienta fueron realizados por **Hanssel** (parte humana), con el apoyo en programación, estructuración del código y diseño del panel por parte de los modelos de inteligencia artificial **Opus** y **Argon**.

