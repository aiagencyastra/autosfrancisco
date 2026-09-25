"use strict";

const $ = (sel) => document.querySelector(sel);
const horaAhora = () => new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });

function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Formato estilo WhatsApp: *negrita*, _cursiva_ y saltos de línea
function formatoWhatsapp(texto) {
  return escapar(texto)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(\S(?:[^*\n]*\S)?)\*/g, "<strong>$1</strong>")
    .replace(/(^|\s)_(\S(?:[^_\n]*\S)?)_(?=\s|$|[.,;:!?])/g, "$1<em>$2</em>")
    .replace(/\n/g, "<br>");
}

async function api(url, opciones = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opciones,
    body: opciones.body ? JSON.stringify(opciones.body) : undefined,
  });
  const datos = await resp.json().catch(() => ({}));
  if (resp.status === 401 && datos.requiere_clave) pedirContrasena();
  if (!resp.ok) throw new Error(datos.error || `Error ${resp.status}`);
  return datos;
}

// Versión online: la demo puede estar protegida con contraseña
function pedirContrasena() {
  $("#capa-entrar").hidden = false;
  $("#entrar-clave").focus();
}

$("#form-entrar").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#entrar-error").hidden = true;
  try {
    await api("/api/entrar", { method: "POST", body: { clave: $("#entrar-clave").value } });
    location.reload();
  } catch (err) {
    $("#entrar-error").textContent = err.message;
    $("#entrar-error").hidden = false;
  }
});

function toast(texto) {
  const t = $("#toast");
  t.textContent = texto;
  t.hidden = false;
  clearTimeout(toast.temporizador);
  toast.temporizador = setTimeout(() => (t.hidden = true), 3500);
}

// ------------------------------------------------------------------ pestañas
document.querySelectorAll(".pestana").forEach((boton) =>
  boton.addEventListener("click", () => {
    document.querySelectorAll(".pestana").forEach((b) => b.classList.toggle("activa", b === boton));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("activo", p.id === boton.dataset.pestana));
    if (boton.dataset.pestana === "facturas") cargarFacturas();
  })
);

// ------------------------------------------------------------------ asistente
const NOMBRES_HERRAMIENTAS = {
  facturas_por_periodo: "facturas por periodo",
  facturas_pendientes_cobro: "pendientes de cobro",
  presupuestos_por_estado: "presupuestos por estado",
  detalle_cliente: "ficha de cliente",
  peticiones_sin_presupuestar: "peticiones sin presupuestar",
  consulta_sql: "consulta libre (solo lectura)",
  facturas_por_emitir: "facturas por emitir",
  pedir_aprobacion_emision: "preparar emisión",
  enviar_factura_cliente: "enviar al cliente",
};
const historial = [];
let ocupado = false;

document.querySelectorAll("[data-hora-ahora]").forEach((e) => (e.textContent = horaAhora()));

function anadirBurbuja(html, tipo) {
  const contenedor = $("#mensajes");
  const div = document.createElement("div");
  div.className = `burbuja ${tipo}`;
  const checks = tipo === "saliente" ? '<span class="checks">✓✓</span>' : "";
  div.innerHTML = `${html}<span class="hora">${horaAhora()}${checks}</span>`;
  contenedor.appendChild(div);
  contenedor.scrollTop = contenedor.scrollHeight;
  return div;
}

function marcarHerramientas(nombres) {
  document.querySelectorAll("#herramientas li").forEach((li) =>
    li.classList.toggle("usada", li.dataset.h.split(" ").some((h) => nombres.includes(h))));
}

async function preguntar(texto) {
  texto = texto.trim();
  if (!texto || ocupado) return;
  ocupado = true;
  bloquearEntrada(true);
  $("#entrada").value = "";
  anadirBurbuja(escapar(texto), "saliente");
  historial.push({ rol: "usuario", texto });
  marcarHerramientas([]);

  $("#chat-estado").textContent = "escribiendo…";
  const escribiendo = anadirBurbuja('<span class="escribiendo"><span></span><span></span><span></span></span>', "entrante");
  escribiendo.querySelector(".hora").remove();

  try {
    // El servidor puede responder por pasos (en Netlify cada llamada tiene pocos segundos):
    // mientras diga "continuar", se le devuelve el estado y se muestra qué está consultando.
    let datos = await api("/api/chat", { method: "POST", body: { historial } });
    const consultas = [...(datos.consultas || [])];
    const acciones = [...(datos.acciones || [])];
    for (let i = 0; datos.continuar && i < 10; i++) {
      marcarHerramientas([...new Set(consultas)]);
      $("#chat-estado").textContent = "consultando " + (NOMBRES_HERRAMIENTAS[consultas.at(-1)] || "la base") + "…";
      datos = await api("/api/chat", { method: "POST", body: { historial, estado: datos.estado } });
      consultas.push(...(datos.consultas || []));
      acciones.push(...(datos.acciones || []));
    }
    datos.consultas = consultas;
    escribiendo.remove();
    anadirBurbuja(formatoWhatsapp(datos.texto), "entrante");
    historial.push({ rol: "asistente", texto: datos.texto });
    const usadas = [...new Set(datos.consultas || [])];
    marcarHerramientas(usadas);
    if (usadas.length) {
      const nota = document.createElement("div");
      nota.className = "consultado";
      nota.textContent = "🔍 Consultado en la base: " + usadas.map((n) => NOMBRES_HERRAMIENTAS[n] || n).join(", ");
      $("#mensajes").appendChild(nota);
      $("#mensajes").scrollTop = $("#mensajes").scrollHeight;
    }
    acciones.forEach(mostrarAccion);
  } catch (e) {
    escribiendo.remove();
    historial.pop(); // la pregunta sin respuesta no entra en el historial
    anadirBurbuja("⚠️ " + escapar(e.message), "entrante error");
  } finally {
    $("#chat-estado").textContent = "en línea";
    ocupado = false;
    bloquearEntrada(false);
    $("#entrada").focus();
  }
}

// ------------------------------------------------------------------ facturas desde el chat
const refFactura = (id) => "F-" + String(id).padStart(4, "0");

function botonesChat(opciones) {
  const caja = document.createElement("div");
  caja.className = "botones-chat";
  opciones.forEach(([texto, accion]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = texto;
    b.addEventListener("click", () => {
      caja.querySelectorAll("button").forEach((x) => (x.disabled = true));
      b.classList.add("elegido");
      accion();
    });
    caja.appendChild(b);
  });
  $("#mensajes").appendChild(caja);
  $("#mensajes").scrollTop = $("#mensajes").scrollHeight;
}

function mostrarAccion(accion) {
  if (accion.tipo === "aprobacion") tarjetaAprobacion(accion);
  if (accion.tipo === "enviada") cargarFacturas().catch(() => {});
}

function tarjetaAprobacion({ factura: f, mensaje }) {
  const i = f.importes;
  const montaje = f.tiene_montaje
    ? `<tr><td>Montaje${f.dias_montaje ? ` (${f.dias_montaje} día${f.dias_montaje === 1 ? "" : "s"})` : ""}</td><td>${i.montaje}</td></tr>`
    : "";
  anadirBurbuja(`
    <div class="tarjeta-factura">
      <div class="tf-titulo">🧾 ${refFactura(f.id)} · ${escapar(f.cliente.nombre)}</div>
      <div class="tf-servicio">${escapar(f.servicio)} · ${escapar(f.descripcion)}</div>
      <table>
        <tr><td>Transporte</td><td>${i.transporte}</td></tr>${montaje}
        <tr class="sub"><td>Base</td><td>${i.base}</td></tr>
        <tr class="sub"><td>IVA 21%</td><td>${i.iva}</td></tr>
        <tr class="total"><td>Total</td><td>${i.total}</td></tr>
      </table>
      <div class="tf-pregunta">${escapar(mensaje)}</div>
    </div>`, "entrante con-tarjeta");
  botonesChat([["Sí", () => aprobarDesdeChat(f, true)], ["No", () => aprobarDesdeChat(f, false)]]);
}

async function aprobarDesdeChat(f, aprobada) {
  anadirBurbuja(aprobada ? "Sí" : "No", "saliente");
  historial.push({ rol: "usuario", texto: aprobada ? "Sí" : "No" });
  try {
    const datos = await api(`/api/facturas/${f.id}/aprobar`, { method: "POST", body: { aprobada } });
    if (!datos.emitida) {
      const texto = `Vale, la factura a ${f.cliente.nombre} no se emite.`;
      anadirBurbuja(escapar(texto), "entrante");
      historial.push({ rol: "asistente", texto });
    } else {
      const texto = `Hecho: factura ${refFactura(f.id)} a ${f.cliente.nombre} emitida por ${f.importes.total}. ¿Se la envío al cliente?`;
      anadirBurbuja(`
        <a class="documento" href="${datos.pdf}" target="_blank" rel="noopener">
          <span class="doc-icono">PDF</span>
          <span><b>factura_${refFactura(f.id)}.pdf</b><small>Toca para abrir</small></span>
        </a>${formatoWhatsapp(texto)}`, "entrante");
      historial.push({ rol: "asistente", texto: `${texto} (PDF generado)` });
      botonesChat([["Enviar al cliente", () => enviarDesdeChat(f)], ["Ahora no", () => {
        historial.push({ rol: "usuario", texto: "Ahora no" });
        anadirBurbuja("Ahora no", "saliente");
      }]]);
    }
  } catch (e) {
    anadirBurbuja("⚠️ " + escapar(e.message), "entrante error");
  }
  cargarFacturas().catch(() => {});
}

async function enviarDesdeChat(f) {
  anadirBurbuja("Enviar al cliente", "saliente");
  historial.push({ rol: "usuario", texto: "Envíasela al cliente" });
  try {
    const datos = await api(`/api/facturas/${f.id}/enviar`, { method: "POST" });
    const texto = `Enviada a ${datos.email} con el PDF adjunto. (En la demo el envío es simulado: no sale ningún correo.)`;
    anadirBurbuja("✉️ " + escapar(texto), "entrante");
    historial.push({ rol: "asistente", texto });
  } catch (e) {
    anadirBurbuja("⚠️ " + escapar(e.message), "entrante error");
  }
  cargarFacturas().catch(() => {});
}

function bloquearEntrada(si) {
  $(".enviar").disabled = si;
  document.querySelectorAll(".sugerencia").forEach((b) => (b.disabled = si));
}

$("#formulario").addEventListener("submit", (e) => {
  e.preventDefault();
  preguntar($("#entrada").value);
});

async function cargarConfig() {
  const cfg = await api("/api/config");
  if (cfg.requiere_clave && !cfg.autorizado) pedirContrasena();
  const caja = $("#sugerencias");
  cfg.preguntas.forEach((p) => {
    const b = document.createElement("button");
    b.className = "sugerencia";
    b.type = "button";
    b.textContent = p;
    b.addEventListener("click", () => preguntar(p));
    caja.appendChild(b);
  });
  $("#aviso-clave").hidden = cfg.hay_clave;
}

// ------------------------------------------------------------------ facturas
let seleccionada = null;
let pendienteDeAprobar = null;

async function cargarFacturas() {
  const datos = await api("/api/facturas");
  pintarLista($("#lista-pendientes"), datos.pendientes, "No quedan facturas aceptadas por emitir.");
  pintarLista($("#lista-emitidas"), datos.emitidas, "Todavía no se ha emitido ninguna.");
  $("#contador-facturas").textContent = datos.pendientes.length || "";
  pintarRegistro(datos.registro);
  if (seleccionada) {
    const actual = [...datos.pendientes, ...datos.emitidas].find((f) => f.id === seleccionada);
    if (actual) pintarVistaPrevia(actual);
  }
}

function pintarLista(contenedor, facturas, textoVacio) {
  contenedor.innerHTML = "";
  if (!facturas.length) {
    contenedor.innerHTML = `<div class="vacio">${textoVacio}</div>`;
    return;
  }
  facturas.forEach((f) => {
    const b = document.createElement("button");
    b.className = "tarjeta" + (f.id === seleccionada ? " seleccionada" : "");
    const etiquetas = f.enviada_demo
      ? '<span class="etiqueta envio">enviada</span>'
      : f.emitida_demo ? '<span class="etiqueta ok">emitida</span>' : "";
    b.innerHTML = `
      <span class="cliente">${escapar(f.cliente.nombre)}</span>
      <span class="total">${escapar(f.importes.total)}</span>
      <span class="meta">F-${String(f.id).padStart(4, "0")} · ${escapar(f.servicio)} · ${fechaCorta(f.fecha)}${etiquetas}</span>`;
    b.addEventListener("click", () => {
      seleccionada = f.id;
      document.querySelectorAll(".tarjeta").forEach((t) => t.classList.remove("seleccionada"));
      b.classList.add("seleccionada");
      pintarVistaPrevia(f);
    });
    contenedor.appendChild(b);
  });
}

function fechaCorta(iso) {
  const [a, m, d] = iso.split("-");
  return `${d}/${m}/${a}`;
}

function pintarVistaPrevia(f) {
  const vp = $("#vista-previa");
  vp.classList.remove("vacia");
  const i = f.importes;
  const montaje = f.tiene_montaje
    ? `<tr><td>Montaje${f.dias_montaje ? ` (${f.dias_montaje} día${f.dias_montaje === 1 ? "" : "s"})` : ""}</td><td>${i.montaje}</td></tr>`
    : "";
  let acciones;
  if (!f.emitida_demo) {
    acciones = `<button class="boton primario" id="emitir">Emitir factura</button>
                <button class="boton secundario" disabled title="Primero hay que emitirla">Enviar al cliente</button>`;
  } else {
    acciones = `<a class="boton-pdf" href="/api/facturas/${f.id}/pdf" target="_blank">📄 Ver PDF</a>
                <button class="boton secundario" id="enviar-cliente">${f.enviada_demo ? "Reenviar al cliente" : "Enviar al cliente"}</button>
                <span class="estado-texto">${f.enviada_demo ? `Enviada a ${escapar(f.enviada_demo.email)} a las ${f.enviada_demo.hora} (simulado)` : "Emitida en la demo"}</span>`;
  }
  vp.innerHTML = `
    <div class="vp-cabecera">
      <div>
        <div class="vp-logo">MONTELIER</div>
        <div class="vp-empresa">NIF: pendiente<br>Dirección: pendiente</div>
      </div>
      <div class="vp-titulo">
        <h3>FACTURA</h3>
        <div>Ref. interna F-${String(f.id).padStart(4, "0")} · Presupuesto P-${String(f.presupuesto_id).padStart(4, "0")}</div>
        <div>Fecha del servicio: ${fechaCorta(f.fecha)}</div>
      </div>
    </div>
    <div class="vp-bloques">
      <div><small>CLIENTE</small><b>${escapar(f.cliente.nombre)}</b><br>${escapar(f.cliente.direccion)}<br>${escapar(f.cliente.email)} · ${escapar(f.cliente.telefono)}</div>
      <div><small>SERVICIO</small><b>${escapar(f.servicio)}</b><br>${escapar(f.descripcion)}<br>${escapar(f.direccion_servicio)}</div>
    </div>
    <table class="vp-tabla">
      <tr><td>Transporte</td><td>${i.transporte}</td></tr>
      ${montaje}
      <tr class="sub"><td>Base imponible</td><td>${i.base}</td></tr>
      <tr class="sub"><td>IVA 21%</td><td>${i.iva}</td></tr>
      <tr class="total"><td>TOTAL</td><td>${i.total}</td></tr>
    </table>
    <div class="vp-acciones">${acciones}</div>`;

  $("#emitir")?.addEventListener("click", () => solicitarAprobacion(f));
  $("#enviar-cliente")?.addEventListener("click", () => enviarCliente(f));
}

function pintarRegistro(registro) {
  const ol = $("#registro");
  if (!registro.length) {
    ol.innerHTML = '<li class="vacio">Sin actividad todavía.</li>';
    return;
  }
  const iconos = { whatsapp: "📱", ok: "✅", no: "✋", envio: "✉️", info: "ℹ️" };
  ol.innerHTML = registro.slice().reverse()
    .map((r) => `<li><time>${r.hora}</time><span>${iconos[r.tipo] || "•"} ${escapar(r.texto)}</span></li>`)
    .join("");
}

async function solicitarAprobacion(f) {
  $("#emitir").disabled = true;
  try {
    const datos = await api(`/api/facturas/${f.id}/solicitar`, { method: "POST" });
    pendienteDeAprobar = f;
    $("#whatsapp-texto").innerHTML = `${escapar(datos.mensaje)}<span class="hora">${horaAhora()}</span>`;
    document.querySelectorAll(".botones-whatsapp button").forEach((b) => (b.disabled = false));
    $("#capa-whatsapp").hidden = false;
    cargarFacturas();
  } catch (e) {
    toast(e.message);
    $("#emitir").disabled = false;
  }
}

async function responderWhatsapp(aprobada) {
  const f = pendienteDeAprobar;
  if (!f) return;
  document.querySelectorAll(".botones-whatsapp button").forEach((b) => (b.disabled = true));
  try {
    const datos = await api(`/api/facturas/${f.id}/aprobar`, { method: "POST", body: { aprobada } });
    $("#capa-whatsapp").hidden = true;
    pendienteDeAprobar = null;
    if (datos.emitida) {
      toast(`Factura a ${f.cliente.nombre} emitida. PDF generado.`);
    } else {
      toast("Francisco ha dicho que no: la factura no se emite.");
    }
    await cargarFacturas();
  } catch (e) {
    toast(e.message);
    document.querySelectorAll(".botones-whatsapp button").forEach((b) => (b.disabled = false));
  }
}

async function enviarCliente(f) {
  try {
    const datos = await api(`/api/facturas/${f.id}/enviar`, { method: "POST" });
    toast(`Factura enviada a ${datos.email} (simulado, no sale ningún correo).`);
    await cargarFacturas();
  } catch (e) {
    toast(e.message);
  }
}

$("#whatsapp-si").addEventListener("click", () => responderWhatsapp(true));
$("#whatsapp-no").addEventListener("click", () => responderWhatsapp(false));

$("#reiniciar").addEventListener("click", async () => {
  if (!confirm("¿Volver a dejar todas las facturas como pendientes de emitir?")) return;
  await api("/api/demo/reiniciar", { method: "POST" });
  seleccionada = null;
  $("#vista-previa").className = "vista-previa vacia";
  $("#vista-previa").innerHTML = "<p>Selecciona una factura para ver la vista previa.</p>";
  cargarFacturas();
});

cargarConfig().catch(() => {});
cargarFacturas().catch(() => {}); // sin contraseña todavía: se carga al entrar
