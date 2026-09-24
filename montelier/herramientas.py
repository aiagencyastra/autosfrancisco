"""Herramientas que el asistente puede usar. Todas leen la base en solo lectura.

Cada herramienta devuelve un dict serializable a JSON con los importes ya
calculados (IVA incluido) y ya formateados en español, para que el modelo no
tenga que hacer cuentas.
"""
import re
import sqlite3
import unicodedata
from datetime import date

from .dinero import desglose, desglose_formateado, formato_eur, sumar_desgloses

MAX_FILAS_SQL = 200


class ErrorHerramienta(Exception):
    """Error que se devuelve al modelo como tool_result con is_error."""


# ---------------------------------------------------------------- utilidades

def _fecha(valor, campo):
    try:
        return date.fromisoformat(str(valor)).isoformat()
    except (TypeError, ValueError):
        raise ErrorHerramienta(f"'{campo}' debe ser una fecha AAAA-MM-DD (recibido: {valor!r})")


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip()


def _importes(fila) -> dict:
    return desglose(fila["importe_transporte"], fila["importe_montaje"])


def _resumen(desgloses) -> dict:
    suma = sumar_desgloses(desgloses)
    return {
        "numero": len(desgloses),
        "base_sin_iva": formato_eur(suma["base"]),
        "iva_21": formato_eur(suma["iva"]),
        "total_con_iva": formato_eur(suma["total"]),
        "_valores": {k: float(v) for k, v in suma.items()},
    }


def _factura(fila) -> dict:
    d = _importes(fila)
    return {
        "factura_id": fila["id"],
        "fecha": fila["fecha"],
        "cliente": fila["cliente"],
        "estado_cobro": fila["estado"],
        "emitida": "sí" if fila["emitida"] else "no",
        **desglose_formateado(d),
    }, d


SQL_FACTURAS = """
    SELECT f.id, f.fecha, f.importe_transporte, f.importe_montaje, f.estado, f.emitida,
           c.nombre AS cliente, p.id AS presupuesto_id
    FROM facturas f
    JOIN presupuestos p ON p.id = f.presupuesto_id
    JOIN clientes c ON c.id = p.cliente_id
"""


# ---------------------------------------------------------------- herramientas

def facturas_por_periodo(con, desde, hasta, estado_cobro=None):
    desde, hasta = _fecha(desde, "desde"), _fecha(hasta, "hasta")
    if estado_cobro not in (None, "", "pendiente", "cobrada"):
        raise ErrorHerramienta("estado_cobro debe ser 'pendiente' o 'cobrada'")
    sql = SQL_FACTURAS + " WHERE f.emitida = 1 AND f.fecha BETWEEN ? AND ?"
    params = [desde, hasta]
    if estado_cobro:
        sql += " AND f.estado = ?"
        params.append(estado_cobro)
    filas = con.execute(sql + " ORDER BY f.fecha, f.id", params).fetchall()
    facturas, desgloses = zip(*[_factura(f) for f in filas]) if filas else ((), ())
    sin_emitir = con.execute(
        "SELECT COUNT(*) FROM facturas WHERE emitida = 0 AND fecha BETWEEN ? AND ?", (desde, hasta)
    ).fetchone()[0]
    return {
        "periodo": {"desde": desde, "hasta": hasta},
        "criterio": "Solo facturas emitidas, por fecha de factura",
        "resumen": _resumen(list(desgloses)),
        "facturas": list(facturas),
        "aceptadas_sin_emitir_en_periodo": sin_emitir,
    }


def facturas_pendientes_cobro(con):
    filas = con.execute(
        SQL_FACTURAS + " WHERE f.emitida = 1 AND f.estado = 'pendiente' ORDER BY f.fecha, f.id"
    ).fetchall()
    hoy = date.today()
    facturas, desgloses = [], []
    for f in filas:
        datos, d = _factura(f)
        datos["dias_desde_factura"] = (hoy - date.fromisoformat(f["fecha"])).days
        facturas.append(datos)
        desgloses.append(d)
    return {"resumen": _resumen(desgloses), "facturas": facturas}


def presupuestos_por_estado(con, estado=None, desde=None, hasta=None):
    if estado not in (None, "", "pendiente", "aceptado", "rechazado"):
        raise ErrorHerramienta("estado debe ser 'pendiente', 'aceptado' o 'rechazado'")
    sql = """SELECT p.*, c.nombre AS cliente FROM presupuestos p
             JOIN clientes c ON c.id = p.cliente_id WHERE 1=1"""
    params = []
    if estado:
        sql += " AND p.estado = ?"
        params.append(estado)
    if desde:
        sql += " AND p.fecha >= ?"
        params.append(_fecha(desde, "desde"))
    if hasta:
        sql += " AND p.fecha <= ?"
        params.append(_fecha(hasta, "hasta"))
    filas = con.execute(sql + " ORDER BY p.fecha, p.id", params).fetchall()
    presupuestos, desgloses = [], []
    for p in filas:
        d = _importes(p)
        presupuestos.append(_presupuesto(p, d))
        desgloses.append(d)
    por_estado = {}
    for p in presupuestos:
        por_estado[p["estado"]] = por_estado.get(p["estado"], 0) + 1
    return {"filtro": {"estado": estado or "todos", "desde": desde, "hasta": hasta},
            "resumen": _resumen(desgloses), "cuantos_por_estado": por_estado,
            "presupuestos": presupuestos}


def _presupuesto(p, d) -> dict:
    return {
        "presupuesto_id": p["id"],
        "fecha": p["fecha"],
        "cliente": p["cliente"] if "cliente" in p.keys() else None,
        "servicio": "transporte y montaje" if p["tipo_servicio"] == "transporte_montaje" else "transporte",
        "dias_montaje": p["dias_montaje"],
        "estado": p["estado"],
        "descripcion": p["comentario"],
        "direccion": p["direccion"],
        **desglose_formateado(d),
    }


def buscar_clientes(con, nombre):
    buscado = _normalizar(nombre)
    if not buscado:
        raise ErrorHerramienta("Indica un nombre (o parte del nombre) del cliente")
    palabras = buscado.split()
    return [c for c in con.execute("SELECT * FROM clientes ORDER BY nombre").fetchall()
            if all(p in _normalizar(c["nombre"]) for p in palabras)]


def detalle_cliente(con, nombre):
    encontrados = buscar_clientes(con, nombre)
    if not encontrados:
        return {"encontrado": False, "mensaje": f"No hay ningún cliente que coincida con '{nombre}'"}
    if len(encontrados) > 1:
        return {"encontrado": False, "mensaje": "Hay varios clientes que coinciden; pregunta cuál",
                "coincidencias": [c["nombre"] for c in encontrados]}
    c = encontrados[0]
    presupuestos, desgloses_p = [], []
    for p in con.execute("SELECT * FROM presupuestos WHERE cliente_id = ? ORDER BY fecha, id", (c["id"],)):
        d = _importes(p)
        datos = _presupuesto(p, d)
        datos.pop("cliente")
        presupuestos.append(datos)
        desgloses_p.append(d)
    facturas, desgloses_f = [], []
    for f in con.execute(SQL_FACTURAS + " WHERE c.id = ? ORDER BY f.fecha, f.id", (c["id"],)):
        datos, d = _factura(f)
        datos.pop("cliente")
        facturas.append(datos)
        desgloses_f.append(d)
    return {
        "encontrado": True,
        "cliente": {k: c[k] for k in ("id", "nombre", "email", "telefono", "direccion")},
        "presupuestos": {"resumen": _resumen(desgloses_p), "lista": presupuestos},
        "facturas": {"resumen": _resumen(desgloses_f), "lista": facturas},
    }


def peticiones_sin_presupuestar(con, desde, hasta):
    desde, hasta = _fecha(desde, "desde"), _fecha(hasta, "hasta")
    filas = con.execute(
        """SELECT * FROM peticiones WHERE presupuestada = 0 AND fecha_peticion BETWEEN ? AND ?
           ORDER BY fecha_peticion, id""", (desde, hasta)).fetchall()
    return {
        "periodo": {"desde": desde, "hasta": hasta},
        "numero": len(filas),
        "peticiones": [{k: f[k] for k in ("id", "comercial", "cliente_nombre", "descripcion",
                                          "fecha_peticion", "fecha_servicio")} for f in filas],
    }


def consulta_sql(con, sql):
    """Consulta libre. La conexión es de solo lectura: cualquier escritura falla en SQLite."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise ErrorHerramienta("La consulta está vacía")
    if ";" in sql:
        raise ErrorHerramienta("Solo se permite una sentencia")
    try:
        cursor = con.execute(sql)
        columnas = [c[0] for c in cursor.description or []]
        filas = cursor.fetchmany(MAX_FILAS_SQL + 1)
    except sqlite3.Error as e:
        raise ErrorHerramienta(f"La base es de solo lectura o la consulta no es válida: {e}")
    return {
        "aviso": "Importes de la base SIN IVA. Si los muestras con IVA, calcula 21% por factura.",
        "columnas": columnas,
        "filas": [list(f) for f in filas[:MAX_FILAS_SQL]],
        "truncado": len(filas) > MAX_FILAS_SQL,
    }


# ---------------------------------------------------------------- definiciones para la API

_FECHA = {"type": "string", "description": "Fecha AAAA-MM-DD"}

DEFINICIONES = [
    {
        "name": "facturas_por_periodo",
        "description": "Facturas EMITIDAS entre dos fechas (ambas incluidas) con número de facturas, "
                       "base sin IVA, IVA 21% y total con IVA ya calculados. Indica también cuántas "
                       "facturas aceptadas quedan sin emitir en el periodo. Úsala para '¿cuánto hemos "
                       "facturado este mes?' y similares.",
        "input_schema": {
            "type": "object",
            "properties": {
                "desde": _FECHA,
                "hasta": _FECHA,
                "estado_cobro": {"type": "string", "enum": ["pendiente", "cobrada"],
                                 "description": "Opcional: filtrar por estado de cobro"},
            },
            "required": ["desde", "hasta"],
        },
    },
    {
        "name": "facturas_pendientes_cobro",
        "description": "Todas las facturas emitidas que están pendientes de cobro, con cliente, fecha, "
                       "días transcurridos y total con IVA, más el total pendiente.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "presupuestos_por_estado",
        "description": "Presupuestos filtrados por estado (pendiente, aceptado, rechazado) y/o por fecha "
                       "del presupuesto, con importes sin IVA, IVA y total.",
        "input_schema": {
            "type": "object",
            "properties": {
                "estado": {"type": "string", "enum": ["pendiente", "aceptado", "rechazado"]},
                "desde": _FECHA,
                "hasta": _FECHA,
            },
        },
    },
    {
        "name": "detalle_cliente",
        "description": "Ficha de un cliente buscado por nombre o parte del nombre (sin importar tildes "
                       "ni mayúsculas): datos de contacto, todos sus presupuestos y sus facturas.",
        "input_schema": {
            "type": "object",
            "properties": {"nombre": {"type": "string", "description": "Nombre o parte del nombre"}},
            "required": ["nombre"],
        },
    },
    {
        "name": "peticiones_sin_presupuestar",
        "description": "Peticiones de los comerciales que aún no se han presupuestado, recibidas entre "
                       "dos fechas (por fecha de petición, ambas incluidas).",
        "input_schema": {
            "type": "object",
            "properties": {"desde": _FECHA, "hasta": _FECHA},
            "required": ["desde", "hasta"],
        },
    },
    {
        "name": "consulta_sql",
        "description": "ÚLTIMO RECURSO: una única consulta SELECT de SQLite sobre la base (solo lectura; "
                       "cualquier intento de modificar datos da error). Úsala solo si ninguna otra "
                       "herramienta sirve. Tablas: clientes(id, nombre, email, telefono, direccion); "
                       "presupuestos(id, cliente_id, tipo_servicio 'transporte'|'transporte_montaje', "
                       "importe_transporte, importe_montaje (puede ser NULL), dias_montaje, fecha, "
                       "estado 'pendiente'|'aceptado'|'rechazado', direccion, comentario); "
                       "facturas(id, presupuesto_id, fecha, importe_transporte, importe_montaje, "
                       "estado 'pendiente'|'cobrada', emitida 0|1); peticiones(id, comercial, "
                       "cliente_nombre, descripcion, fecha_peticion, fecha_servicio, presupuestada 0|1). "
                       "Fechas en texto AAAA-MM-DD. Todos los importes SIN IVA.",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
]

FUNCIONES = {
    "facturas_por_periodo": facturas_por_periodo,
    "facturas_pendientes_cobro": facturas_pendientes_cobro,
    "presupuestos_por_estado": presupuestos_por_estado,
    "detalle_cliente": detalle_cliente,
    "peticiones_sin_presupuestar": peticiones_sin_presupuestar,
    "consulta_sql": consulta_sql,
}


def ejecutar(con, nombre: str, argumentos: dict) -> dict:
    if nombre not in FUNCIONES:
        raise ErrorHerramienta(f"Herramienta desconocida: {nombre}")
    if not isinstance(argumentos, dict):
        raise ErrorHerramienta("Argumentos no válidos")
    try:
        return FUNCIONES[nombre](con, **argumentos)
    except TypeError as e:
        raise ErrorHerramienta(f"Parámetros incorrectos para {nombre}: {e}")
