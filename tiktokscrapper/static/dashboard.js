const fmt = (n) => {
    if (n === null || n === undefined || n === "" || isNaN(n)) return "—";
    n = Number(n);
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toFixed(1) + "B";
    if (abs >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (abs >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toLocaleString("es");
};

document.querySelectorAll("[data-fmt]").forEach((el) => {
    const v = el.textContent.trim();
    if (v !== "") {
        el.title = Number(v).toLocaleString("es");
        el.textContent = fmt(v);
    }
});

const selScrape = document.getElementById("sel-scrape");
if (selScrape) {
    selScrape.addEventListener("change", () => {
        window.location.href = `/dashboard/${encodeURIComponent(window.DASH_DATA.username)}?scrape=${selScrape.value}`;
    });
}

if (window.Chart) {
    Chart.defaults.color = "#9aa3b2";
    Chart.defaults.borderColor = "#2a2f3a";
    const D = window.DASH_DATA || {};

    const ctxTimeline = document.getElementById("chart-timeline");
    if (ctxTimeline && D.linea_tiempo && D.linea_tiempo.length) {
        new Chart(ctxTimeline, {
            type: "line",
            data: {
                labels: D.linea_tiempo.map((p) => (p.fecha || "").slice(5, 16)),
                datasets: [
                    {
                        label: "Vistas",
                        data: D.linea_tiempo.map((p) => p.vistas || 0),
                        borderColor: "#fe2c55",
                        backgroundColor: "rgba(254, 44, 85, 0.15)",
                        fill: true,
                        tension: 0.3,
                        yAxisID: "y",
                    },
                    {
                        label: "ER %",
                        data: D.linea_tiempo.map((p) => p.er || 0),
                        borderColor: "#25f4ee",
                        backgroundColor: "transparent",
                        tension: 0.3,
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    y: { position: "left", ticks: { callback: (v) => fmt(v) } },
                    y1: {
                        position: "right",
                        grid: { drawOnChartArea: false },
                        ticks: { callback: (v) => v + "%" },
                    },
                },
            },
        });
    }

    const ctxDur = document.getElementById("chart-duracion");
    if (ctxDur && D.duraciones) {
        new Chart(ctxDur, {
            type: "bar",
            data: {
                labels: D.duraciones.map((x) => `${x.rango} (${x.posts})`),
                datasets: [
                    {
                        label: "Vistas promedio",
                        data: D.duraciones.map((x) => x.vistas_promedio || 0),
                        backgroundColor: "#fe2c55",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { ticks: { callback: (v) => fmt(v) } } },
            },
        });
    }

    const ctxDias = document.getElementById("chart-dias");
    if (ctxDias && D.dias) {
        new Chart(ctxDias, {
            type: "bar",
            data: {
                labels: D.dias.map((x) => x.dia.slice(0, 3)),
                datasets: [
                    {
                        label: "Vistas promedio",
                        data: D.dias.map((x) => x.vistas_promedio || 0),
                        backgroundColor: "#25f4ee",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { ticks: { callback: (v) => fmt(v) } } },
            },
        });
    }

    const ctxHoras = document.getElementById("chart-horas");
    if (ctxHoras && D.horas) {
        new Chart(ctxHoras, {
            type: "bar",
            data: {
                labels: D.horas.map((x) => `${String(x.hora).padStart(2, "0")}h`),
                datasets: [
                    {
                        label: "Vistas promedio",
                        data: D.horas.map((x) => x.vistas_promedio || 0),
                        backgroundColor: "#3ddc97",
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { ticks: { callback: (v) => fmt(v) } } },
            },
        });
    }

    const ctxTags = document.getElementById("chart-hashtags");
    if (ctxTags && D.hashtags && D.hashtags.length) {
        new Chart(ctxTags, {
            type: "bar",
            data: {
                labels: D.hashtags.map((h) => `#${h.tag} (${h.usos})`),
                datasets: [
                    {
                        label: "Vistas promedio",
                        data: D.hashtags.map((h) => h.vistas_promedio || 0),
                        backgroundColor: "#ffc857",
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                scales: { x: { ticks: { callback: (v) => fmt(v) } } },
            },
        });
    }

    const ctxHist = document.getElementById("chart-historial");
    if (ctxHist && D.historial && D.historial.length >= 2) {
        new Chart(ctxHist, {
            type: "line",
            data: {
                labels: D.historial.map((h) => h.fecha),
                datasets: [
                    {
                        label: "Seguidores",
                        data: D.historial.map((h) => h.seguidores || 0),
                        borderColor: "#fe2c55",
                        tension: 0.25,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { ticks: { callback: (v) => fmt(v) } } },
            },
        });
    }
}

const inputTexto = document.getElementById("filtro-texto");
const selOrden = document.getElementById("filtro-orden");
const tabla = document.getElementById("tabla-posts");

function actualizarTabla() {
    if (!tabla) return;
    const tbody = tabla.querySelector("tbody");
    const filas = Array.from(tbody.querySelectorAll("tr"));
    const q = (inputTexto ? inputTexto.value : "").trim().toLowerCase();
    const [campo, dir] = (selOrden ? selOrden.value : "fecha-desc").split("-");

    filas.forEach((tr) => {
        const coincide = !q || (tr.dataset.texto || "").includes(q);
        tr.style.display = coincide ? "" : "none";
    });

    filas.sort((a, b) => {
        const va = Number(a.dataset[campo] || 0);
        const vb = Number(b.dataset[campo] || 0);
        return dir === "asc" ? va - vb : vb - va;
    });

    filas.forEach((tr) => tbody.appendChild(tr));
}

if (inputTexto) inputTexto.addEventListener("input", actualizarTabla);
if (selOrden) selOrden.addEventListener("change", actualizarTabla);

