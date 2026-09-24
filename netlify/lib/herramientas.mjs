// Herramientas del asistente (misma lógica que montelier/herramientas.py).
// Devuelven los importes ya calculados (IVA incluido) y formateados, para que el modelo no haga cuentas.
import { desglose, desgloseFormateado, formatoEur, sumarDesgloses } from "./dinero.mjs";
import { hoyEspana } from "./base.mjs";

const MAX_FILAS_SQL = 200;

export class ErrorHerramienta extends Error {}

// ---------------------------------------------------------------- utilidades
function fecha(valor, campo) {
  if (typeof valor !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(valor) ||
      Number.isNaN(Date.parse(`${valor}T00:00:00Z`)) || new Date(`${valor}T00:00:00Z`).toISOString().slice(0, 10) !== valor) {
    throw new ErrorHerramienta(`'${campo}' debe ser una fecha AAAA-MM-DD (recibido: ${JSON.stringify(valor)})`);
  }
  return valor;
}

export const normalizar = (texto) =>
  (texto || "").normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();

const importes = (f) => desglose(f.importe_transporte, f.importe_montaje);

function resumen(desgloses) {
  const s = sumarDesgloses(desgloses);
  return { numero: desgloses.length, base_sin_iva: formatoEur(s.base), iva_21: formatoEur(s.iva),
           total_con_iva: formatoEur(s.total) };
}

function factura(f) {
  const d = importes(f);
  return [{ factura_id: f.id, fecha: f.fecha, cliente: f.cliente, estado_cobro: f.estado,
            emitida: f.emitida ? "sí" : "no", ...desgloseFormateado(d) }, d];
}

function presupuesto(p, d) {
  return { presupuesto_id: p.id, fecha: p.fecha, cliente: p.cliente ?? null,
    servicio: p.tipo_servicio === "transporte_montaje" ? "transporte y montaje" : "transporte",
    dias_montaje: p.dias_montaje, estado: p.estado, descripcion: p.comentario, direccion: p.direccion,
    ...desgloseFormateado(d) };
}

const SQL_FACTURAS = `
  SELECT f.id, f.fecha, f.importe_transporte, f.importe_montaje, f.estado, f.emitida,
         c.nombre AS cliente, p.id AS presupuesto_id
  FROM facturas f JOIN presupuestos p ON p.id = f.presupuesto_id JOIN clientes c ON c.id = p.cliente_id`;

// ---------------------------------------------------------------- herramientas
export function facturas_por_periodo(db, { desde, hasta, estado_cobro } = {}) {
  desde = fecha(desde, "desde"); hasta = fecha(hasta, "hasta");
  if (![undefined, null, "", "pendiente", "cobrada"].includes(estado_cobro)) {
    throw new ErrorHerramienta("estado_cobro debe ser 'pendiente' o 'cobrada'");
  }
  let sql = `${SQL_FACTURAS} WHERE f.emitida = 1 AND f.fecha BETWEEN ? AND ?`;
  const params = [desde, hasta];
  if (estado_cobro) { sql += " AND f.estado = ?"; params.push(estado_cobro); }
  const filas = db.prepare(`${sql} ORDER BY f.fecha, f.id`).all(...params).map(factura);
  const sinEmitir = db.prepare("SELECT COUNT(*) AS n FROM facturas WHERE emitida = 0 AND fecha BETWEEN ? AND ?")
    .get(desde, hasta).n;
  return { periodo: { desde, hasta }, criterio: "Solo facturas emitidas, por fecha de factura",
           resumen: resumen(filas.map((x) => x[1])), facturas: filas.map((x) => x[0]),
           aceptadas_sin_emitir_en_periodo: sinEmitir };
}

export function facturas_pendientes_cobro(db, _args = {}, hoy = hoyEspana()) {
  const filas = db.prepare(`${SQL_FACTURAS} WHERE f.emitida = 1 AND f.estado = 'pendiente' ORDER BY f.fecha, f.id`).all();
  const facturas = [], desgloses = [];
  for (const f of filas) {
    const [datos, d] = factura(f);
    datos.dias_desde_factura = Math.round((Date.parse(hoy) - Date.parse(f.fecha)) / 86400000);
    facturas.push(datos); desgloses.push(d);
  }
  return { resumen: resumen(desgloses), facturas };
}

export function presupuestos_por_estado(db, { estado, desde, hasta } = {}) {
  if (![undefined, null, "", "pendiente", "aceptado", "rechazado"].includes(estado)) {
    throw new ErrorHerramienta("estado debe ser 'pendiente', 'aceptado' o 'rechazado'");
  }
  let sql = "SELECT p.*, c.nombre AS cliente FROM presupuestos p JOIN clientes c ON c.id = p.cliente_id WHERE 1=1";
  const params = [];
  if (estado) { sql += " AND p.estado = ?"; params.push(estado); }
  if (desde) { sql += " AND p.fecha >= ?"; params.push(fecha(desde, "desde")); }
  if (hasta) { sql += " AND p.fecha <= ?"; params.push(fecha(hasta, "hasta")); }
  const presupuestos = [], desgloses = [], porEstado = {};
  for (const p of db.prepare(`${sql} ORDER BY p.fecha, p.id`).all(...params)) {
    const d = importes(p);
    presupuestos.push(presupuesto(p, d)); desgloses.push(d);
    porEstado[p.estado] = (porEstado[p.estado] || 0) + 1;
  }
  return { filtro: { estado: estado || "todos", desde: desde ?? null, hasta: hasta ?? null },
           resumen: resumen(desgloses), cuantos_por_estado: porEstado, presupuestos };
}

export function buscarClientes(db, nombre) {
  const buscado = normalizar(nombre);
  if (!buscado) throw new ErrorHerramienta("Indica un nombre (o parte del nombre) del cliente");
  const palabras = buscado.split(" ");
  return db.prepare("SELECT * FROM clientes ORDER BY nombre").all()
    .filter((c) => palabras.every((p) => normalizar(c.nombre).includes(p)));
}

export function detalle_cliente(db, { nombre } = {}) {
  const encontrados = buscarClientes(db, nombre);
  if (!encontrados.length) return { encontrado: false, mensaje: `No hay ningún cliente que coincida con '${nombre}'` };
  if (encontrados.length > 1) {
    return { encontrado: false, mensaje: "Hay varios clientes que coinciden; pregunta cuál",
             coincidencias: encontrados.map((c) => c.nombre) };
  }
  const c = encontrados[0];
  const presupuestos = [], dp = [];
  for (const p of db.prepare("SELECT * FROM presupuestos WHERE cliente_id = ? ORDER BY fecha, id").all(c.id)) {
    const d = importes(p);
    const datos = presupuesto(p, d);
    delete datos.cliente;
    presupuestos.push(datos); dp.push(d);
  }
  const facturas = [], df = [];
  for (const f of db.prepare(`${SQL_FACTURAS} WHERE c.id = ? ORDER BY f.fecha, f.id`).all(c.id)) {
    const [datos, d] = factura(f);
    delete datos.cliente;
    facturas.push(datos); df.push(d);
  }
  return { encontrado: true,
    cliente: { id: c.id, nombre: c.nombre, email: c.email, telefono: c.telefono, direccion: c.direccion },
    presupuestos: { resumen: resumen(dp), lista: presupuestos },
    facturas: { resumen: resumen(df), lista: facturas } };
}

export function peticiones_sin_presupuestar(db, { desde, hasta } = {}) {
  desde = fecha(desde, "desde"); hasta = fecha(hasta, "hasta");
  const filas = db.prepare(`SELECT id, comercial, cliente_nombre, descripcion, fecha_peticion, fecha_servicio
    FROM peticiones WHERE presupuestada = 0 AND fecha_peticion BETWEEN ? AND ? ORDER BY fecha_peticion, id`)
    .all(desde, hasta).map((f) => ({ ...f }));
  return { periodo: { desde, hasta }, numero: filas.length, peticiones: filas };
}

export function consulta_sql(db, { sql } = {}) {
  sql = String(sql ?? "").trim().replace(/;+\s*$/, "").trim();
  if (!sql) throw new ErrorHerramienta("La consulta está vacía");
  if (sql.includes(";")) throw new ErrorHerramienta("Solo se permite una sentencia");
  if (!/^(select|with)\b/i.test(sql)) throw new ErrorHerramienta("Solo se permiten consultas SELECT: la base es de solo lectura");
  let columnas, filas;
  try {
    const st = db.prepare(sql);
    st.setReturnArrays(true);
    columnas = st.columns().map((c) => c.name);
    filas = [];
    for (const f of st.iterate()) { filas.push(f); if (filas.length > MAX_FILAS_SQL) break; }
  } catch (e) {
    throw new ErrorHerramienta(`La base es de solo lectura o la consulta no es válida: ${e.message}`);
  }
  return { aviso: "Importes de la base SIN IVA. Si los muestras con IVA, calcula 21% por factura.",
           columnas, filas: filas.slice(0, MAX_FILAS_SQL), truncado: filas.length > MAX_FILAS_SQL };
}

// ---------------------------------------------------------------- definiciones para la API
const FECHA = { type: "string", description: "Fecha AAAA-MM-DD" };

export const DEFINICIONES = [
  { name: "facturas_por_periodo",
    description: "Facturas EMITIDAS entre dos fechas (ambas incluidas) con número de facturas, base sin IVA, " +
      "IVA 21% y total con IVA ya calculados. Indica también cuántas facturas aceptadas quedan sin emitir en el " +
      "periodo. Úsala para '¿cuánto hemos facturado este mes?' y similares.",
    input_schema: { type: "object", properties: { desde: FECHA, hasta: FECHA,
      estado_cobro: { type: "string", enum: ["pendiente", "cobrada"], description: "Opcional: filtrar por estado de cobro" } },
      required: ["desde", "hasta"] } },
  { name: "facturas_pendientes_cobro",
    description: "Todas las facturas emitidas que están pendientes de cobro, con cliente, fecha, días " +
      "transcurridos y total con IVA, más el total pendiente.",
    input_schema: { type: "object", properties: {} } },
  { name: "presupuestos_por_estado",
    description: "Presupuestos filtrados por estado (pendiente, aceptado, rechazado) y/o por fecha del " +
      "presupuesto, con importes sin IVA, IVA y total.",
    input_schema: { type: "object", properties: {
      estado: { type: "string", enum: ["pendiente", "aceptado", "rechazado"] }, desde: FECHA, hasta: FECHA } } },
  { name: "detalle_cliente",
    description: "Ficha de un cliente buscado por nombre o parte del nombre (sin importar tildes ni " +
      "mayúsculas): datos de contacto, todos sus presupuestos y sus facturas.",
    input_schema: { type: "object", properties: { nombre: { type: "string", description: "Nombre o parte del nombre" } },
      required: ["nombre"] } },
  { name: "peticiones_sin_presupuestar",
    description: "Peticiones de los comerciales que aún no se han presupuestado, recibidas entre dos fechas " +
      "(por fecha de petición, ambas incluidas).",
    input_schema: { type: "object", properties: { desde: FECHA, hasta: FECHA }, required: ["desde", "hasta"] } },
  { name: "consulta_sql",
    description: "ÚLTIMO RECURSO: una única consulta SELECT de SQLite sobre la base (solo lectura; cualquier " +
      "intento de modificar datos da error). Úsala solo si ninguna otra herramienta sirve. Tablas: " +
      "clientes(id, nombre, email, telefono, direccion); presupuestos(id, cliente_id, tipo_servicio " +
      "'transporte'|'transporte_montaje', importe_transporte, importe_montaje (puede ser NULL), dias_montaje, " +
      "fecha, estado 'pendiente'|'aceptado'|'rechazado', direccion, comentario); facturas(id, presupuesto_id, " +
      "fecha, importe_transporte, importe_montaje, estado 'pendiente'|'cobrada', emitida 0|1); peticiones(id, " +
      "comercial, cliente_nombre, descripcion, fecha_peticion, fecha_servicio, presupuestada 0|1). Fechas en " +
      "texto AAAA-MM-DD. Todos los importes SIN IVA.",
    input_schema: { type: "object", properties: { sql: { type: "string" } }, required: ["sql"] } },
];

const FUNCIONES = { facturas_por_periodo, facturas_pendientes_cobro, presupuestos_por_estado,
                    detalle_cliente, peticiones_sin_presupuestar, consulta_sql };

export function ejecutar(db, nombre, argumentos) {
  if (!Object.hasOwn(FUNCIONES, nombre)) throw new ErrorHerramienta(`Herramienta desconocida: ${nombre}`);
  if (!argumentos || typeof argumentos !== "object" || Array.isArray(argumentos)) {
    throw new ErrorHerramienta("Argumentos no válidos");
  }
  return FUNCIONES[nombre](db, argumentos);
}
