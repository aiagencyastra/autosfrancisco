"""Crea la base SQLite de ejemplo que imita la estructura de la de Montelier.

Las fechas se calculan respecto al día de hoy para que "este mes" y
"esta semana" siempre tengan datos cuando se enseñe la demo.

    python crear_base.py            # crea datos/montelier.db si no existe o es de otro día
    python crear_base.py --forzar   # la regenera siempre
"""
import calendar
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from montelier.db import RUTA_BD

ESQUEMA = """
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    email TEXT,
    telefono TEXT,
    direccion TEXT
);
CREATE TABLE presupuestos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    tipo_servicio TEXT NOT NULL CHECK (tipo_servicio IN ('transporte', 'transporte_montaje')),
    importe_transporte REAL NOT NULL,
    importe_montaje REAL,
    dias_montaje INTEGER,
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'aceptado', 'rechazado')),
    direccion TEXT,
    comentario TEXT
);
CREATE TABLE facturas (
    id INTEGER PRIMARY KEY,
    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id),
    fecha TEXT NOT NULL,
    importe_transporte REAL NOT NULL,
    importe_montaje REAL,
    estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'cobrada')),
    emitida INTEGER NOT NULL CHECK (emitida IN (0, 1))
);
CREATE TABLE peticiones (
    id INTEGER PRIMARY KEY,
    comercial TEXT NOT NULL,
    cliente_nombre TEXT NOT NULL,
    descripcion TEXT,
    fecha_peticion TEXT NOT NULL,
    fecha_servicio TEXT,
    presupuestada INTEGER NOT NULL CHECK (presupuestada IN (0, 1))
);
"""

# Los datos de ejemplo están en datos_ejemplo.json (los usa también la versión web en Netlify)
_DATOS = json.loads((Path(__file__).resolve().parent / "datos_ejemplo.json").read_text(encoding="utf-8"))

CLIENTES = [(c["nombre"], c["email"], c["telefono"], c["direccion"]) for c in _DATOS["clientes"]]

# Presupuestos aceptados que tienen factura: meses_atras (0 = mes actual), fracción del mes
# para la fecha de la factura, estado de cobro y si está emitida
FACTURADOS = [(f["cliente"], f["tipo"], f["transporte"], f["montaje"], f["dias"], f["comentario"],
               f["meses_atras"], f["fraccion"], f["cobro"], f["emitida"]) for f in _DATOS["facturados"]]

OTROS_PRESUPUESTOS = [(p["cliente"], p["tipo"], p["transporte"], p["montaje"], p["dias"], p["estado"],
                       p["dias_atras"], p["comentario"]) for p in _DATOS["otros_presupuestos"]]

COMERCIALES = _DATOS["comerciales"]

# dias_desde_lunes: respecto al lunes de esta semana (negativo = semanas anteriores)
PETICIONES = [(p["comercial"], p["cliente"], p["descripcion"], p["dias_desde_lunes"],
               p["dias_hasta_servicio"], p["presupuestada"]) for p in _DATOS["peticiones"]]


def restar_meses(hoy: date, meses: int) -> date:
    anio, mes = hoy.year, hoy.month - meses
    while mes < 1:
        mes += 12
        anio -= 1
    return date(anio, mes, 1)


def fecha_en_mes(hoy: date, meses_atras: int, fraccion: float) -> date:
    inicio = restar_meses(hoy, meses_atras)
    ultimo = hoy.day if meses_atras == 0 else calendar.monthrange(inicio.year, inicio.month)[1]
    dia = min(ultimo, max(1, round(ultimo * fraccion)))
    return inicio.replace(day=dia)


def direccion_de(cliente_id: int) -> str:
    return CLIENTES[cliente_id - 1][3]


def construir(hoy: date):
    presupuestos = []  # dicts sin id
    facturas = []
    for (cli, tipo, tra, mon, dias, com, mes, frac, cobro, emitida) in FACTURADOS:
        f_factura = fecha_en_mes(hoy, mes, frac)
        p = dict(cliente_id=cli, tipo_servicio=tipo, importe_transporte=tra, importe_montaje=mon,
                 dias_montaje=dias, fecha=f_factura - timedelta(days=12), estado="aceptado",
                 direccion=direccion_de(cli), comentario=com)
        presupuestos.append(p)
        facturas.append(dict(presupuesto=p, fecha=f_factura, importe_transporte=tra,
                             importe_montaje=mon, estado=cobro, emitida=emitida))
    for (cli, tipo, tra, mon, dias, estado, atras, com) in OTROS_PRESUPUESTOS:
        presupuestos.append(dict(cliente_id=cli, tipo_servicio=tipo, importe_transporte=tra,
                                 importe_montaje=mon, dias_montaje=dias,
                                 fecha=hoy - timedelta(days=atras), estado=estado,
                                 direccion=direccion_de(cli), comentario=com))

    presupuestos.sort(key=lambda p: (p["fecha"], p["cliente_id"]))
    for i, p in enumerate(presupuestos, start=1):
        p["id"] = i
    facturas.sort(key=lambda f: (f["fecha"], f["presupuesto"]["id"]))
    for i, f in enumerate(facturas, start=1):
        f["id"] = i
        f["presupuesto_id"] = f.pop("presupuesto")["id"]

    lunes = hoy - timedelta(days=hoy.weekday())
    peticiones = []
    for i, (com, cli, desc, d_lunes, d_servicio, presup) in enumerate(PETICIONES, start=1):
        # Las de esta semana nunca quedan en el futuro
        f_pet = lunes + timedelta(days=min(d_lunes, hoy.weekday())) if d_lunes >= 0 else lunes + timedelta(days=d_lunes)
        peticiones.append(dict(id=i, comercial=COMERCIALES[com], cliente_nombre=cli, descripcion=desc,
                               fecha_peticion=f_pet, fecha_servicio=f_pet + timedelta(days=d_servicio + 7),
                               presupuestada=presup))
    return presupuestos, facturas, peticiones


def crear(ruta: Path, hoy: date | None = None) -> Path:
    hoy = hoy or date.today()
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.unlink(missing_ok=True)
    presupuestos, facturas, peticiones = construir(hoy)

    con = sqlite3.connect(temporal)
    con.executescript(ESQUEMA)
    con.executemany("INSERT INTO clientes VALUES (?, ?, ?, ?, ?)",
                    [(i, *c) for i, c in enumerate(CLIENTES, start=1)])
    con.executemany(
        "INSERT INTO presupuestos VALUES (:id, :cliente_id, :tipo_servicio, :importe_transporte, "
        ":importe_montaje, :dias_montaje, :fecha, :estado, :direccion, :comentario)",
        [{**p, "fecha": p["fecha"].isoformat()} for p in presupuestos])
    con.executemany(
        "INSERT INTO facturas VALUES (:id, :presupuesto_id, :fecha, :importe_transporte, "
        ":importe_montaje, :estado, :emitida)",
        [{**f, "fecha": f["fecha"].isoformat()} for f in facturas])
    con.executemany(
        "INSERT INTO peticiones VALUES (:id, :comercial, :cliente_nombre, :descripcion, "
        ":fecha_peticion, :fecha_servicio, :presupuestada)",
        [{**p, "fecha_peticion": p["fecha_peticion"].isoformat(),
          "fecha_servicio": p["fecha_servicio"].isoformat()} for p in peticiones])
    con.commit()
    con.close()
    temporal.replace(ruta)
    ruta.with_name("generada.txt").write_text(hoy.isoformat())
    return ruta


def necesita_regenerar(ruta: Path, hoy: date) -> bool:
    marca = ruta.with_name("generada.txt")
    return not ruta.exists() or not marca.exists() or marca.read_text().strip() != hoy.isoformat()


if __name__ == "__main__":
    hoy = date.today()
    if "--forzar" in sys.argv or necesita_regenerar(RUTA_BD, hoy):
        crear(RUTA_BD, hoy)
        # Base nueva: el estado de la demo (facturas emitidas) ya no aplica
        RUTA_BD.with_name("estado_demo.json").unlink(missing_ok=True)
        print(f"Base de ejemplo creada en {RUTA_BD}")
    else:
        print(f"Base de ejemplo al día: {RUTA_BD}")
