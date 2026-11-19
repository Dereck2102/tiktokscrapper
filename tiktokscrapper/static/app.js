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

const form = document.getElementById("form-scrape");
const btn = document.getElementById("btn-scrape");
const msg = document.getElementById("form-msg");
const caja = document.getElementById("trabajos");
let hayActivos = false;
const cuentasConocidas = new Set(
    [...document.querySelectorAll("[data-usuario]")].map((t) => t.dataset.usuario)
);

function leerOpciones() {
    const fd = new FormData(form);
    const datos = Object.fromEntries(fd.entries());
    datos.headless = !fd.has("mostrar_navegador");
    datos.humanizar = fd.has("humanizar");
    datos.bloquear_multimedia = fd.has("bloquear_multimedia");
    datos.sesion_persistente = fd.has("sesion_persistente");
    delete datos.mostrar_navegador;
    localStorage.setItem("opciones_scrape", JSON.stringify(datos));
    return datos;
}

function restaurarOpciones() {
    try {
        const d = JSON.parse(localStorage.getItem("opciones_scrape") || "{}");
        for (const [k, v] of Object.entries(d)) {
            if (k === "usernames") continue;
            const el = form.elements[k];
            if (!el) continue;
            if (el instanceof RadioNodeList) {
                [...el].forEach((r) => (r.checked = r.value === v));
            } else if (el.type === "checkbox") {
                el.checked = !!v;
            } else {
                el.value = v;
            }
        }
        if ("headless" in d) {
            form.elements["mostrar_navegador"].checked = !d.headless;
        }
    } catch (_) {}
}
restaurarOpciones();

async function lanzar(datos) {
    btn.disabled = true;
    msg.textContent = "Enviando...";
    try {
        const r = await fetch("/api/scrape", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(datos),
        });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || "Error");
        msg.textContent = `${j.trabajos.length} tarea(s) en cola.`;
        refrescar();
    } catch (e) {
        msg.textContent = e.message;
    } finally {
        btn.disabled = false;
    }
}

form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    lanzar(leerOpciones());
});

function pintar(trabajos) {
    if (!trabajos.length) {
        caja.innerHTML = '<div class="vacio">Sin tareas registradas.</div>';
        return;
    }
    caja.innerHTML = trabajos
        .map(
            (t) => `
        <div class="trabajo ${t.estado}">
            <div class="fila">
                <b>@${t.username}</b>
                <span class="estado ${t.estado}">${t.estado.replace("_", " ")} · ${t.modo}</span>
            </div>
            <div class="barra"><div style="width:${t.progreso}%"></div></div>
            <div class="fila">
                <span class="ayuda" style="margin:0">${t.mensaje || ""}</span>
                ${t.scrape_id ? `<a class="btn peq" href="/dashboard/${t.username}?scrape=${t.scrape_id}">Ver dashboard</a>` : ""}
            </div>
        </div>`
        )
        .join("");
}

async function refrescar() {
    try {
        const r = await fetch("/api/jobs");
        const trabajos = await r.json();
        pintar(trabajos);
        const activos = trabajos.some(
            (t) => t.estado === "en_cola" || t.estado === "ejecutando"
        );
        const nuevas = trabajos.filter(
            (t) => t.estado === "completado" && !cuentasConocidas.has(t.username)
        );
        if (hayActivos && !activos && nuevas.length) location.reload();
        hayActivos = activos;
    } catch (_) {}
}

setInterval(refrescar, 1500);
refrescar();

document.getElementById("btn-limpiar").addEventListener("click", async () => {
    await fetch("/api/jobs/limpiar", { method: "POST" });
    refrescar();
});

document.querySelectorAll("[data-reescrapear]").forEach((b) =>
    b.addEventListener("click", () => {
        const datos = leerOpciones();
        datos.usernames = b.dataset.reescrapear;
        lanzar(datos);
        window.scrollTo({ top: 0, behavior: "smooth" });
    })
);

document.querySelectorAll("[data-eliminar]").forEach((b) =>
    b.addEventListener("click", async () => {
        const u = b.dataset.eliminar;
        if (!confirm(`¿Eliminar todos los registros de @${u}?`)) return;
        await fetch(`/api/cuentas/${encodeURIComponent(u)}/eliminar`, {
            method: "POST",
        });
        location.reload();
    })
);

