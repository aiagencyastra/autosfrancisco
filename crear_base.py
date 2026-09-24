"""Crea la base SQLite de ejemplo que imita la estructura de la de Montelier.

Las fechas se calculan respecto al día de hoy para que "este mes" y
"esta semana" siempre tengan datos cuando se enseñe la demo.

    python crear_base.py            # crea datos/montelier.db si no existe o es de otro día
    python crear_base.py --forzar   # la regenera siempre
"""
import calendar
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

CLIENTES = [
    # nombre, email, telefono, direccion
    ("Interiorismo Blau SL", "administracion@interiorismoblau.es", "932 145 870", "C/ de Provença 214, 08036 Barcelona"),
    ("Hotel Costa Daurada SA", "compras@hotelcostadaurada.es", "977 381 225", "Passeig de Jaume I 32, 43840 Salou (Tarragona)"),
    ("Oficinas Diagonal Coworking SL", "facturas@diagonalcowork.es", "934 102 336", "Av. Diagonal 480, 08006 Barcelona"),
    ("Clínica Dental Sant Gervasi SLP", "gestion@dentalsantgervasi.es", "932 117 904", "C/ de Muntaner 390, 08021 Barcelona"),
    ("Restaurante El Serrallo SL", "info@restaurantserrallo.es", "977 240 518", "Moll de Pescadors 12, 43004 Tarragona"),
    ("Escola Bressol Els Pins SCCL", "direccio@bressolelspins.cat", "977 315 662", "C/ de Sant Joan 18, 43201 Reus (Tarragona)"),
    ("Logística Camp de Tarragona SL", "operaciones@logisticacamp.es", "977 552 190", "Pol. Ind. Riu Clar, C/ del Coure 5, 43006 Tarragona"),
    ("Galería Arte Born SL", "hola@galeriaborn.es", "933 196 427", "C/ del Rec 44, 08003 Barcelona"),
    ("Marta Puig Soler", "marta.puig.soler@correo.es", "654 218 903", "C/ de Sant Domènec 7, 08172 Sant Cugat del Vallès (Barcelona)"),
    ("Jordi Ferrer Vidal", "jferrervidal@correo.es", "619 447 205", "C/ de Sants 155, 3º 2ª, 08028 Barcelona"),
    ("Laura Martínez Roca", "lauramartinezroca@correo.es", "687 330 158", "Av. de la Diputació 88, 43850 Cambrils (Tarragona)"),
    ("Andreu Casals Pons", "andreu.casals@correo.es", "622 905 471", "Rambla Nova 101, 5º 1ª, 43001 Tarragona"),
]

# Presupuestos aceptados que tienen factura.
# (cliente, tipo, transporte, montaje, dias, comentario, mes (0=actual, 1=anterior...),
#  fracción del mes para la factura, estado de cobro, emitida)
FACTURADOS = [
    (1, "transporte_montaje", 640.00, 1180.00, 2, "Mobiliario de showroom, 2 plantas", 2, 0.15, "cobrada", 1),
    (4, "transporte_montaje", 420.00, 865.50, 1, "Sillones de gabinete y recepción", 2, 0.40, "cobrada", 1),
    (9, "transporte", 285.00, None, None, "Mudanza de piso a Sant Cugat, 3 dormitorios", 2, 0.62, "cobrada", 1),
    (7, "transporte", 1340.00, None, None, "Traslado de 18 estanterías industriales", 2, 0.90, "cobrada", 1),
    (2, "transporte_montaje", 980.00, 2350.00, 4, "Renovación mobiliario 24 habitaciones planta 3", 1, 0.10, "cobrada", 1),
    (3, "transporte_montaje", 510.00, 1420.00, 2, "Puestos de trabajo y mamparas zona B", 1, 0.33, "cobrada", 1),
    (10, "transporte_montaje", 190.00, 240.00, 1, "Cocina desmontada: transporte y montaje", 1, 0.55, "cobrada", 1),
    (5, "transporte", 365.00, None, None, "Cámara frigorífica y mesas de terraza", 1, 0.78, "pendiente", 1),
    (8, "transporte_montaje", 720.00, 655.00, 1, "Montaje exposición temporal, peanas y vitrinas", 1, 0.93, "pendiente", 1),
    (6, "transporte_montaje", 330.00, 495.00, 1, "Mobiliario aula de 2 años", 0, 0.20, "cobrada", 1),
    (11, "transporte", 245.00, None, None, "Traslado de muebles a segunda residencia", 0, 0.50, "pendiente", 1),
    (12, "transporte_montaje", 210.00, 385.00, 1, "Armario empotrado y dormitorio juvenil", 0, 0.80, "pendiente", 1),
    # Aceptadas y sin emitir todavía
    (3, "transporte_montaje", 460.00, 1234.55, 2, "Sala de reuniones y 12 puestos nuevos", 0, 0.60, "pendiente", 0),
    (1, "transporte", 395.00, None, None, "Recogida de muestras de proveedor en Mataró", 0, 0.90, "pendiente", 0),
    (7, "transporte_montaje", 890.00, 1560.00, 3, "Altillo metálico y estanterías picking", 0, 1.00, "pendiente", 0),
]

# Resto de presupuestos: (cliente, tipo, transporte, montaje, dias, estado, días atrás, comentario)
OTROS_PRESUPUESTOS = [
    (2, "transporte_montaje", 1150.00, 2890.00, 4, "pendiente", 6, "Mobiliario de terraza y 30 hamacas para temporada"),
    (2, "transporte", 640.00, None, None, "rechazado", 52, "Traslado de colchones a almacén de Reus"),
    (4, "transporte", 180.00, None, None, "pendiente", 3, "Sillón dental de reserva a almacén"),
    (5, "transporte_montaje", 410.00, 720.00, 2, "pendiente", 9, "Barra y mobiliario de la nueva sala"),
    (8, "transporte", 520.00, None, None, "rechazado", 70, "Obras para feria en Madrid (cliente buscó otra opción)"),
    (9, "transporte_montaje", 150.00, 210.00, 1, "pendiente", 2, "Montaje de estanterías y escritorio"),
    (10, "transporte", 260.00, None, None, "rechazado", 33, "Vaciado de trastero"),
    (11, "transporte_montaje", 275.00, 340.00, 1, "aceptado", 4, "Dormitorio completo, servicio la semana que viene"),
    (12, "transporte", 195.00, None, None, "pendiente", 12, "Piano vertical a 1ª planta sin ascensor"),
    (6, "transporte_montaje", 280.00, 460.00, 1, "pendiente", 16, "Mobiliario del comedor"),
]

COMERCIALES = ["Sergi", "Núria", "Pau"]

PETICIONES = [
    # comercial, cliente, descripción, días desde el lunes de esta semana, días hasta el servicio, presupuestada
    (0, "Hotel Costa Daurada SA", "Cambio de mobiliario del lobby y 2 sofás grandes", 0, 21, 0),
    (1, "Restaurante Can Roig SL", "Transporte de cocina industrial desde Vilanova", 1, 14, 0),
    (2, "Marta Puig Soler", "Montaje de armario PAX de 3 módulos", 2, 10, 0),
    (0, "Centro Médico Rambla SL", "Traslado de consulta completa, sin montaje", 3, 25, 0),
    (1, "Oficinas Diagonal Coworking SL", "Ampliación: 8 puestos más en planta 2", 1, 30, 1),
    (2, "Galería Arte Born SL", "Retirada de la exposición y almacenaje", -4, 12, 0),
    (0, "Laura Martínez Roca", "Dormitorio completo con montaje", -9, -2, 1),
    (1, "Logística Camp de Tarragona SL", "Altillo metálico y estanterías de picking", -15, -5, 1),
]


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
