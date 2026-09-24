// Base SQLite de ejemplo (misma estructura y datos que crear_base.py) y conexión de solo lectura.
import { existsSync, renameSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import DATOS from "../../datos_ejemplo.json" with { type: "json" };

const ESQUEMA = `
CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, email TEXT, telefono TEXT, direccion TEXT);
CREATE TABLE presupuestos (
  id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  tipo_servicio TEXT NOT NULL CHECK (tipo_servicio IN ('transporte', 'transporte_montaje')),
  importe_transporte REAL NOT NULL, importe_montaje REAL, dias_montaje INTEGER, fecha TEXT NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'aceptado', 'rechazado')), direccion TEXT, comentario TEXT);
CREATE TABLE facturas (
  id INTEGER PRIMARY KEY, presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id), fecha TEXT NOT NULL,
  importe_transporte REAL NOT NULL, importe_montaje REAL,
  estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'cobrada')), emitida INTEGER NOT NULL CHECK (emitida IN (0, 1)));
CREATE TABLE peticiones (
  id INTEGER PRIMARY KEY, comercial TEXT NOT NULL, cliente_nombre TEXT NOT NULL, descripcion TEXT,
  fecha_peticion TEXT NOT NULL, fecha_servicio TEXT, presupuestada INTEGER NOT NULL CHECK (presupuestada IN (0, 1)));
`;

// ---------------------------------------------------------------- fechas (texto AAAA-MM-DD, en UTC)
const aFecha = (iso) => new Date(`${iso}T00:00:00Z`);
const aIso = (d) => d.toISOString().slice(0, 10);
export const sumarDias = (iso, dias) => { const d = aFecha(iso); d.setUTCDate(d.getUTCDate() + dias); return aIso(d); };
export const diaSemana = (iso) => (aFecha(iso).getUTCDay() + 6) % 7; // lunes = 0, como en Python
export const hoyEspana = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(new Date());
const diasDelMes = (anio, mes) => new Date(Date.UTC(anio, mes, 0)).getUTCDate(); // mes 1-12

// round() de Python redondea al par en los empates (4,5 -> 4)
function redondeoPar(x) {
  const suelo = Math.floor(x);
  const resto = x - suelo;
  if (resto > 0.5) return suelo + 1;
  if (resto < 0.5) return suelo;
  return suelo % 2 === 0 ? suelo : suelo + 1;
}

function fechaEnMes(hoy, mesesAtras, fraccion) {
  let [anio, mes, dia] = hoy.split("-").map(Number);
  mes -= mesesAtras;
  while (mes < 1) { mes += 12; anio -= 1; }
  const ultimo = mesesAtras === 0 ? dia : diasDelMes(anio, mes);
  const d = Math.min(ultimo, Math.max(1, redondeoPar(ultimo * fraccion)));
  return `${anio}-${String(mes).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function construir(hoy) {
  const direccion = (id) => DATOS.clientes[id - 1].direccion;
  const presupuestos = [];
  const facturas = [];
  for (const f of DATOS.facturados) {
    const fFactura = fechaEnMes(hoy, f.meses_atras, f.fraccion);
    const p = { cliente_id: f.cliente, tipo_servicio: f.tipo, importe_transporte: f.transporte,
      importe_montaje: f.montaje, dias_montaje: f.dias, fecha: sumarDias(fFactura, -12), estado: "aceptado",
      direccion: direccion(f.cliente), comentario: f.comentario };
    presupuestos.push(p);
    facturas.push({ presupuesto: p, fecha: fFactura, importe_transporte: f.transporte,
      importe_montaje: f.montaje, estado: f.cobro, emitida: f.emitida });
  }
  for (const p of DATOS.otros_presupuestos) {
    presupuestos.push({ cliente_id: p.cliente, tipo_servicio: p.tipo, importe_transporte: p.transporte,
      importe_montaje: p.montaje, dias_montaje: p.dias, fecha: sumarDias(hoy, -p.dias_atras), estado: p.estado,
      direccion: direccion(p.cliente), comentario: p.comentario });
  }
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  presupuestos.sort((a, b) => cmp(a.fecha, b.fecha) || a.cliente_id - b.cliente_id);
  presupuestos.forEach((p, i) => (p.id = i + 1));
  facturas.sort((a, b) => cmp(a.fecha, b.fecha) || a.presupuesto.id - b.presupuesto.id);
  facturas.forEach((f, i) => { f.id = i + 1; f.presupuesto_id = f.presupuesto.id; delete f.presupuesto; });

  const semana = diaSemana(hoy);
  const lunes = sumarDias(hoy, -semana);
  const peticiones = DATOS.peticiones.map((p, i) => {
    const fPet = p.dias_desde_lunes >= 0 ? sumarDias(lunes, Math.min(p.dias_desde_lunes, semana))
                                        : sumarDias(lunes, p.dias_desde_lunes);
    return { id: i + 1, comercial: DATOS.comerciales[p.comercial], cliente_nombre: p.cliente,
      descripcion: p.descripcion, fecha_peticion: fPet, fecha_servicio: sumarDias(fPet, p.dias_hasta_servicio + 7),
      presupuestada: p.presupuestada };
  });
  return { presupuestos, facturas, peticiones };
}

export function crear(ruta, hoy) {
  const temporal = `${ruta}.tmp`;
  rmSync(temporal, { force: true });
  const { presupuestos, facturas, peticiones } = construir(hoy);
  const db = new DatabaseSync(temporal);
  db.exec(ESQUEMA);
  const insertar = (sql, filas) => { const st = db.prepare(sql); for (const f of filas) st.run(...f); };
  db.exec("BEGIN");
  insertar("INSERT INTO clientes VALUES (?, ?, ?, ?, ?)",
    DATOS.clientes.map((c, i) => [i + 1, c.nombre, c.email, c.telefono, c.direccion]));
  insertar("INSERT INTO presupuestos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", presupuestos.map((p) =>
    [p.id, p.cliente_id, p.tipo_servicio, p.importe_transporte, p.importe_montaje, p.dias_montaje, p.fecha,
     p.estado, p.direccion, p.comentario]));
  insertar("INSERT INTO facturas VALUES (?, ?, ?, ?, ?, ?, ?)", facturas.map((f) =>
    [f.id, f.presupuesto_id, f.fecha, f.importe_transporte, f.importe_montaje, f.estado, f.emitida]));
  insertar("INSERT INTO peticiones VALUES (?, ?, ?, ?, ?, ?, ?)", peticiones.map((p) =>
    [p.id, p.comercial, p.cliente_nombre, p.descripcion, p.fecha_peticion, p.fecha_servicio, p.presupuestada]));
  db.exec("COMMIT");
  db.close();
  renameSync(temporal, ruta);
  return ruta;
}

// Una base por día (fechas relativas a hoy), creada la primera vez que se pide.
export function rutaBase(hoy = hoyEspana()) {
  const ruta = join(tmpdir(), `montelier-${hoy}.db`);
  if (!existsSync(ruta)) crear(ruta, hoy);
  return ruta;
}

// SIEMPRE en solo lectura: la conexión se abre readOnly (SQLite rechaza cualquier escritura)
// y además con PRAGMA query_only.
export function conectar(ruta = rutaBase()) {
  const db = new DatabaseSync(ruta, { readOnly: true });
  db.exec("PRAGMA query_only = ON");
  return db;
}
