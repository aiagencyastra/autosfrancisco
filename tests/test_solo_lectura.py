"""La base del cliente no se puede modificar desde el asistente, ni por instrucciones ni por SQL."""
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from montelier import asistente, herramientas
from montelier.db import conectar

ESCRITURAS = [
    "INSERT INTO clientes (nombre) VALUES ('Intruso')",
    "UPDATE facturas SET estado = 'cobrada'",
    "DELETE FROM presupuestos",
    "DROP TABLE facturas",
    "CREATE TABLE x (a)",
    "ALTER TABLE clientes ADD COLUMN notas TEXT",
    "CREATE INDEX i ON clientes(nombre)",
    "REPLACE INTO clientes (id, nombre) VALUES (1, 'X')",
    "PRAGMA query_only = OFF",
    "PRAGMA writable_schema = ON",
    "ATTACH DATABASE ':memory:' AS otra",
    "VACUUM",
    "WITH x AS (SELECT 1) DELETE FROM facturas",
]


def huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


@pytest.mark.parametrize("sql", ESCRITURAS)
def test_conexion_rechaza_escrituras(bd_fija, sql):
    antes = huella(bd_fija)
    con = conectar(bd_fija)
    with pytest.raises(sqlite3.Error):
        con.execute(sql)
        con.commit()
    con.close()
    assert huella(bd_fija) == antes


@pytest.mark.parametrize("sql", ESCRITURAS)
def test_herramienta_sql_libre_rechaza_escrituras(bd_fija, sql):
    antes = huella(bd_fija)
    con = conectar(bd_fija)
    with pytest.raises(herramientas.ErrorHerramienta):
        herramientas.ejecutar(con, "consulta_sql", {"sql": sql})
    con.close()
    assert huella(bd_fija) == antes


def test_modo_ro_protege_aunque_falle_todo_lo_demas(bd_fija):
    """Sin autorizador ni query_only: la propia apertura mode=ro ya impide escribir."""
    con = sqlite3.connect(f"{bd_fija.resolve().as_uri()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        con.execute("DELETE FROM facturas")
    con.close()


def test_varias_sentencias_rechazadas(bd_fija):
    con = conectar(bd_fija)
    with pytest.raises(herramientas.ErrorHerramienta):
        herramientas.ejecutar(con, "consulta_sql", {"sql": "SELECT 1; DELETE FROM facturas"})
    con.close()


def test_lectura_si_funciona(bd_fija):
    con = conectar(bd_fija)
    r = herramientas.ejecutar(con, "consulta_sql", {"sql": "SELECT COUNT(*) FROM clientes"})
    assert r["filas"] == [[12]]
    con.close()


# --------------------------------------------------------------- bucle completo con un Claude simulado

def _bloque_texto(t):
    return SimpleNamespace(type="text", text=t)


def _bloque_herramienta(i, nombre, entrada):
    return SimpleNamespace(type="tool_use", id=i, name=nombre, input=entrada)


class ClaudeFalso:
    """Simula que el modelo intenta borrar datos y luego responde con texto."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.peticiones = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **kwargs):
        self.peticiones.append(json.loads(json.dumps(kwargs["messages"], default=lambda o: o.__dict__)))
        contenido = self.guion.pop(0)
        motivo = "tool_use" if any(b.type == "tool_use" for b in contenido) else "end_turn"
        return SimpleNamespace(stop_reason=motivo, content=contenido)


def test_asistente_no_puede_modificar_la_base(bd_fija):
    antes = huella(bd_fija)
    falso = ClaudeFalso([
        [_bloque_herramienta("t1", "consulta_sql", {"sql": "DELETE FROM facturas"}),
         _bloque_herramienta("t2", "consulta_sql", {"sql": "UPDATE clientes SET nombre = 'x'"})],
        [_bloque_texto("Desde aquí solo puedo consultar, no modificar.")],
    ])
    r = asistente.responder([{"rol": "usuario", "texto": "Borra todas las facturas"}],
                            cliente=falso, ruta_bd=bd_fija)
    assert r["texto"] == "Desde aquí solo puedo consultar, no modificar."
    resultados = falso.peticiones[1][-1]["content"]
    assert len(resultados) == 2
    assert all(res["is_error"] for res in resultados)
    assert all("solo lectura" in res["content"] for res in resultados)
    assert huella(bd_fija) == antes


def test_herramienta_desconocida_o_argumentos_malos_son_error(bd_fija):
    con = conectar(bd_fija)
    with pytest.raises(herramientas.ErrorHerramienta):
        herramientas.ejecutar(con, "borrar_todo", {})
    with pytest.raises(herramientas.ErrorHerramienta):
        herramientas.ejecutar(con, "facturas_por_periodo", {"desde": "ayer", "hasta": "hoy"})
    with pytest.raises(herramientas.ErrorHerramienta):
        herramientas.ejecutar(con, "facturas_por_periodo", {"desde": "2026-09-01"})
    con.close()
