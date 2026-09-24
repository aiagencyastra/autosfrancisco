// Pruebas de la versión web (Netlify). Mismos criterios que las de Python en tests/.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";
import { PDFDocument } from "pdf-lib";

import { conectar, rutaBase } from "../lib/base.mjs";
import { desglose, formatoEur, sumarDesgloses } from "../lib/dinero.mjs";
import * as h from "../lib/herramientas.mjs";
import { contextoFechas, responder } from "../lib/asistente.mjs";
import { detalleFactura, facturasPorEmitir, generarPdf } from "../lib/factura.mjs";
import { crearApi } from "../functions/api.mjs";

const HOY = "2026-09-24"; // jueves
const RUTA = rutaBase(HOY);
const huella = () => createHash("sha256").update(readFileSync(RUTA)).digest("hex");

// ---------------------------------------------------------------- IVA y redondeos
test("IVA 21 % y redondeo mitad hacia arriba", () => {
  assert.deepEqual(desglose(1000), { transporte: 100000, montaje: 0, base: 100000, iva: 21000, total: 121000 });
  assert.equal(formatoEur(desglose(460, 1234.55).total), "2.050,41 €");
  for (const [base, iva] of [["0.50", 11], ["10.05", 211], ["2.50", 53], ["0.02", 0], ["12.50", 263]]) {
    assert.equal(desglose(base).iva, iva, base);
  }
  assert.equal(desglose(0.1, 0.2).base, 30);
  assert.equal(sumarDesgloses([desglose("0.50"), desglose("0.50")]).iva, 22);
  for (let c = 0; c < 100000; c += 7) { const d = desglose(c / 100); assert.equal(d.total, d.base + d.iva); }
});

test("formato español", () => {
  assert.equal(formatoEur(121000), "1.210,00 €");
  assert.equal(formatoEur(0), "0,00 €");
  assert.equal(formatoEur(123456789), "1.234.567,89 €");
  assert.equal(formatoEur(-4510), "-45,10 €");
});

// ---------------------------------------------------------------- solo lectura
const ESCRITURAS = ["INSERT INTO clientes (nombre) VALUES ('x')", "UPDATE facturas SET estado = 'cobrada'",
  "DELETE FROM presupuestos", "DROP TABLE facturas", "CREATE TABLE x (a)", "ALTER TABLE clientes ADD COLUMN n TEXT",
  "PRAGMA query_only = OFF; DELETE FROM facturas", "WITH x AS (SELECT 1) DELETE FROM facturas", "VACUUM"];

test("la conexión no deja escribir", () => {
  const antes = huella();
  const db = conectar(RUTA);
  for (const sql of ESCRITURAS) assert.throws(() => db.exec(sql), sql);
  db.close();
  assert.equal(huella(), antes);
});

test("la herramienta de SQL libre rechaza escrituras y deja leer", () => {
  const antes = huella();
  const db = conectar(RUTA);
  for (const sql of ESCRITURAS) assert.throws(() => h.ejecutar(db, "consulta_sql", { sql }), h.ErrorHerramienta, sql);
  assert.deepEqual(h.ejecutar(db, "consulta_sql", { sql: "SELECT COUNT(*) FROM clientes" }).filas, [[12]]);
  assert.throws(() => h.ejecutar(db, "borrar_todo", {}), h.ErrorHerramienta);
  assert.throws(() => h.ejecutar(db, "facturas_por_periodo", { desde: "ayer", hasta: "hoy" }), h.ErrorHerramienta);
  db.close();
  assert.equal(huella(), antes);
});

// Claude simulado: intenta borrar y luego responde
function claudeFalso(guion) {
  const peticiones = [];
  return { peticiones, beta: { messages: { create: async (p) => {
    peticiones.push(structuredClone(p.messages));
    const content = guion.shift();
    return { stop_reason: content.some((b) => b.type === "tool_use") ? "tool_use" : "end_turn", content };
  } } } };
}

test("el asistente no puede modificar la base", async () => {
  const antes = huella();
  const cliente = claudeFalso([
    [{ type: "tool_use", id: "t1", name: "consulta_sql", input: { sql: "DELETE FROM facturas" } },
     { type: "tool_use", id: "t2", name: "consulta_sql", input: { sql: "UPDATE clientes SET nombre = 'x'" } }],
    [{ type: "text", text: "Solo puedo consultar." }],
  ]);
  const r = await responder([{ rol: "usuario", texto: "Borra todo" }], { cliente, hoy: HOY, ruta: RUTA });
  assert.equal(r.texto, "Solo puedo consultar.");
  const resultados = cliente.peticiones[1].at(-1).content;
  assert.equal(resultados.length, 2);
  assert.ok(resultados.every((x) => x.is_error));
  assert.equal(huella(), antes);
});

// ---------------------------------------------------------------- las 4 preguntas contra SQL directo
const directa = new DatabaseSync(RUTA, { readOnly: true });
const centimos = (v) => Math.round((v || 0) * 100);
function totalesDirectos(filas) {
  let base = 0, iva = 0;
  for (const f of filas) { const b = centimos(f.importe_transporte) + centimos(f.importe_montaje); base += b; iva += Math.floor((b * 21 + 50) / 100); }
  return { n: filas.length, base: formatoEur(base), iva: formatoEur(iva), total: formatoEur(base + iva) };
}

test("contexto de fechas", () => {
  const t = contextoFechas(HOY);
  assert.ok(t.includes("jueves 24 de septiembre de 2026"));
  assert.ok(t.includes("del 2026-09-21 al 2026-09-27"));
  assert.ok(t.includes("del 2026-09-01 al 2026-09-30"));
});

test("pregunta 1: facturas de este mes", () => {
  const db = conectar(RUTA);
  const r = h.facturas_por_periodo(db, { desde: "2026-09-01", hasta: "2026-09-30" });
  const e = totalesDirectos(directa.prepare("SELECT * FROM facturas WHERE emitida = 1 AND fecha BETWEEN '2026-09-01' AND '2026-09-30'").all());
  assert.deepEqual([r.resumen.numero, r.resumen.base_sin_iva, r.resumen.iva_21, r.resumen.total_con_iva],
                   [e.n, e.base, e.iva, e.total]);
  assert.deepEqual([e.n, e.total], [3, "2.014,65 €"]);
  assert.equal(r.aceptadas_sin_emitir_en_periodo, 3);
  db.close();
});

test("pregunta 2: pendientes de cobro", () => {
  const db = conectar(RUTA);
  const r = h.facturas_pendientes_cobro(db, {}, HOY);
  const filas = directa.prepare("SELECT * FROM facturas WHERE emitida = 1 AND estado = 'pendiente' ORDER BY fecha, id").all();
  assert.deepEqual(r.facturas.map((f) => f.factura_id), filas.map((f) => f.id));
  assert.equal(r.resumen.total_con_iva, totalesDirectos(filas).total);
  assert.equal(r.resumen.total_con_iva, "3.121,80 €");
  db.close();
});

test("pregunta 3: peticiones sin presupuestar esta semana", () => {
  const db = conectar(RUTA);
  const r = h.peticiones_sin_presupuestar(db, { desde: "2026-09-21", hasta: "2026-09-27" });
  const filas = directa.prepare("SELECT id FROM peticiones WHERE presupuestada = 0 AND fecha_peticion BETWEEN '2026-09-21' AND '2026-09-27' ORDER BY fecha_peticion, id").all();
  assert.deepEqual(r.peticiones.map((p) => p.id), filas.map((f) => f.id));
  assert.equal(r.numero, 4);
  db.close();
});

test("pregunta 4: presupuestos de Hotel Costa Daurada", () => {
  const db = conectar(RUTA);
  const r = h.detalle_cliente(db, { nombre: "hotel costa daurada" });
  const filas = directa.prepare("SELECT p.* FROM presupuestos p JOIN clientes c ON c.id = p.cliente_id WHERE c.nombre = 'Hotel Costa Daurada SA' ORDER BY p.fecha, p.id").all();
  assert.deepEqual(r.presupuestos.lista.map((p) => p.presupuesto_id), filas.map((f) => f.id));
  assert.equal(r.presupuestos.resumen.total_con_iva, totalesDirectos(filas).total);
  assert.equal(r.presupuestos.resumen.base_sin_iva, "8.010,00 €");
  assert.equal(h.detalle_cliente(db, { nombre: "galeria arte" }).cliente.nombre, "Galería Arte Born SL");
  assert.equal(h.detalle_cliente(db, { nombre: "Pepito Pérez" }).encontrado, false);
  db.close();
});

// ---------------------------------------------------------------- PDF
test("el PDF se genera para cada factura por emitir", async () => {
  const facturas = facturasPorEmitir(RUTA);
  assert.equal(facturas.length, 3);
  for (const f of facturas) {
    const pdf = await generarPdf(f, HOY);
    assert.equal(pdf.subarray(0, 4).toString(), "%PDF");
    assert.equal((await PDFDocument.load(pdf)).getPageCount(), 1);
  }
  const raro = { ...detalleFactura(12, RUTA), descripcion: "Piano & sofá <grande> · 3º 2ª — 😀 ✓" };
  assert.ok((await generarPdf(raro, HOY)).length > 1000);
});

// ---------------------------------------------------------------- API (flujo de la pestaña Facturas)
function almacenMemoria() {
  const datos = new Map();
  return { get: async (k) => (datos.has(k) ? JSON.parse(datos.get(k)) : null),
           setJSON: async (k, v) => { datos.set(k, JSON.stringify(v)); } };
}
const pedir = (api, ruta, { metodo = "GET", cuerpo, cookie } = {}) => api(new Request(`https://demo.test/api${ruta}`, {
  method: metodo, body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  headers: { "content-type": "application/json", ...(cookie ? { cookie } : {}) } }));

test("flujo emitir → aprobar → enviar sin tocar la base", async () => {
  delete process.env.DEMO_CLAVE;
  const antes = huella();
  const api = crearApi({ almacen: almacenMemoria(), hoy: () => HOY });
  let datos = await (await pedir(api, "/facturas")).json();
  assert.equal(datos.pendientes.length, 3);
  const f = datos.pendientes[0];
  assert.equal((await pedir(api, `/facturas/${f.id}/enviar`, { metodo: "POST" })).status, 409);
  const { mensaje } = await (await pedir(api, `/facturas/${f.id}/solicitar`, { metodo: "POST" })).json();
  assert.equal(mensaje, `Factura a ${f.cliente.nombre}, ${f.importes.total}. ¿La emito?`);
  assert.equal((await (await pedir(api, `/facturas/${f.id}/aprobar`, { metodo: "POST", cuerpo: { aprobada: false } })).json()).emitida, false);
  await pedir(api, `/facturas/${f.id}/solicitar`, { metodo: "POST" });
  const r = await (await pedir(api, `/facturas/${f.id}/aprobar`, { metodo: "POST", cuerpo: { aprobada: true } })).json();
  assert.equal(r.emitida, true);
  const pdf = await pedir(api, `/facturas/${f.id}/pdf`);
  assert.equal(pdf.headers.get("content-type"), "application/pdf");
  assert.equal(Buffer.from(await pdf.arrayBuffer()).subarray(0, 4).toString(), "%PDF");
  assert.equal((await (await pedir(api, `/facturas/${f.id}/enviar`, { metodo: "POST" })).json()).email, f.cliente.email);
  datos = await (await pedir(api, "/facturas")).json();
  assert.equal(datos.pendientes.length, 2);
  assert.deepEqual(datos.registro.map((x) => x.tipo), ["whatsapp", "no", "whatsapp", "ok", "envio"]);
  assert.equal(huella(), antes);
});

test("contraseña de la demo", async () => {
  process.env.DEMO_CLAVE = "secreta";
  try {
    const api = crearApi({ almacen: almacenMemoria(), hoy: () => HOY });
    assert.equal((await pedir(api, "/facturas")).status, 401);
    assert.equal((await (await pedir(api, "/config")).json()).autorizado, false);
    assert.equal((await pedir(api, "/entrar", { metodo: "POST", cuerpo: { clave: "mal" } })).status, 401);
    const ok = await pedir(api, "/entrar", { metodo: "POST", cuerpo: { clave: "secreta" } });
    const cookie = ok.headers.get("set-cookie").split(";")[0];
    assert.equal((await pedir(api, "/facturas", { cookie })).status, 200);
  } finally {
    delete process.env.DEMO_CLAVE;
  }
});

test("chat por pasos con Claude simulado", async () => {
  process.env.ANTHROPIC_API_KEY ||= "prueba";
  const cliente = claudeFalso([
    [{ type: "tool_use", id: "t1", name: "facturas_por_periodo", input: { desde: "2026-09-01", hasta: "2026-09-30" } }],
    [{ type: "text", text: "Llevas 3 facturas: 2.014,65 € con IVA." }],
  ]);
  const api = crearApi({ almacen: almacenMemoria(), hoy: () => HOY, clienteClaude: () => cliente });
  const historial = [{ rol: "usuario", texto: "¿Cuántas facturas llevamos este mes?" }];
  const p1 = await (await pedir(api, "/chat", { metodo: "POST", cuerpo: { historial } })).json();
  assert.equal(p1.continuar, true);
  assert.deepEqual(p1.consultas, ["facturas_por_periodo"]);
  assert.ok(JSON.parse(p1.estado.mensajes.at(-1).content[0].content).resumen.total_con_iva === "2.014,65 €");
  const p2 = await (await pedir(api, "/chat", { metodo: "POST", cuerpo: { historial, estado: p1.estado } })).json();
  assert.equal(p2.texto, "Llevas 3 facturas: 2.014,65 € con IVA.");
});
