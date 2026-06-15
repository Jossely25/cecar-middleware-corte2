from flask import Flask, request, jsonify, Response
from lxml import etree
import psycopg2
from psycopg2.extras import Json, RealDictCursor
import requests
from datetime import datetime
import uuid
import os
import json

app = Flask(__name__)

CLAVE_API = os.environ.get("CLAVE_API", "CECAR-CORTE2-KEY").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
ACADEMICO_URL = os.environ.get("ACADEMICO_URL", "http://localhost:4000/academico/estudiante").rstrip("/")
GESTION_URL = os.environ.get("GESTION_URL", "http://localhost:4000/gestion-estudiantil/estudiante").rstrip("/")
TUTORIAS_URL = os.environ.get("TUTORIAS_URL", "http://localhost:4000/tutorias/asignatura").rstrip("/")
BIENESTAR_URL = os.environ.get("BIENESTAR_URL", "http://localhost:4000/bienestar/estudiante").rstrip("/")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XSD_PATH = os.path.join(BASE_DIR, "xsd", "solicitud_academica.xsd")

PROGRAMAS_VALIDOS = {
    "Ingeniería de Sistemas",
    "Administración de Empresas",
    "Contaduría Pública",
    "Derecho",
    "Psicología"
}

ESTADOS_VALIDOS = {"nueva", "en_revision", "cerrada", "derivada_asesoria"}
URGENCIAS_VALIDAS = {"baja", "media", "alta"}


def ahora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def generar_codigo(prefijo: str) -> str:
    return f"{prefijo}-{str(uuid.uuid4())[:8].upper()}"


def validar_api_key() -> bool:
    return request.headers.get("X-API-key", "").strip() == CLAVE_API


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurado")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS solicitudes (
        id SERIAL PRIMARY KEY,
        solicitud_id VARCHAR(30) UNIQUE NOT NULL,
        input_format VARCHAR(10) NOT NULL,
        codigo_estudiante VARCHAR(20) NOT NULL,
        nombre_estudiante VARCHAR(120) NOT NULL,
        correo_institucional VARCHAR(120) NOT NULL,
        programa VARCHAR(120) NOT NULL,
        asignatura VARCHAR(120) NOT NULL,
        tema VARCHAR(150) NOT NULL,
        descripcion TEXT NOT NULL,
        nivel_urgencia VARCHAR(20) NOT NULL,
        fecha_solicitud DATE NOT NULL,
        estado VARCHAR(30) NOT NULL,
        clasificacion VARCHAR(20),
        tutor_asignado VARCHAR(120),
        bienestar_prioridad VARCHAR(50),
        consolidado_json JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eventos (
        id SERIAL PRIMARY KEY,
        solicitud_id VARCHAR(30) NOT NULL,
        tipo_evento VARCHAR(80) NOT NULL,
        payload JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS errores_calidad (
        id SERIAL PRIMARY KEY,
        solicitud_id VARCHAR(30) NOT NULL,
        regla VARCHAR(120) NOT NULL,
        campo VARCHAR(80) NOT NULL,
        mensaje TEXT NOT NULL,
        valor_detectado TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
]


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    for sql in CREATE_TABLES_SQL:
        cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


@app.before_request
def ensure_db_ready():
    if request.endpoint == "home":
        return
    init_db()


def registrar_evento(solicitud_id: str, tipo_evento: str, payload: dict):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO eventos (solicitud_id, tipo_evento, payload) VALUES (%s, %s, %s)",
        (solicitud_id, tipo_evento, Json(payload))
    )
    conn.commit()
    cur.close()
    conn.close()


def registrar_errores(solicitud_id: str, errores: list[dict]):
    conn = get_db_connection()
    cur = conn.cursor()
    for error in errores:
        cur.execute(
            """
            INSERT INTO errores_calidad (solicitud_id, regla, campo, mensaje, valor_detectado)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                solicitud_id,
                error["regla"],
                error["campo"],
                error["mensaje"],
                str(error.get("valor_detectado", ""))
            )
        )
    conn.commit()
    cur.close()
    conn.close()


def guardar_solicitud(solicitud_id: str, input_format: str, data: dict, consolidado: dict):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO solicitudes (
            solicitud_id, input_format, codigo_estudiante, nombre_estudiante,
            correo_institucional, programa, asignatura, tema, descripcion,
            nivel_urgencia, fecha_solicitud, estado, clasificacion,
            tutor_asignado, bienestar_prioridad, consolidado_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            solicitud_id,
            input_format,
            data["codigo_estudiante"],
            data["nombre_estudiante"],
            data["correo_institucional"],
            data["programa"],
            data["asignatura"],
            data["tema"],
            data["descripcion"],
            data["nivel_urgencia"],
            data["fecha_solicitud"],
            data["estado"],
            consolidado["clasificacion"],
            consolidado["tutorias"].get("tutor_asignado", ""),
            consolidado["bienestar"].get("prioridad", ""),
            Json(consolidado)
        )
    )
    conn.commit()
    cur.close()
    conn.close()


def obtener_solicitud_db(solicitud_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM solicitudes WHERE solicitud_id = %s", (solicitud_id,))
    solicitud = cur.fetchone()
    cur.close()
    conn.close()
    return solicitud


def es_duplicada(data: dict) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM solicitudes
        WHERE codigo_estudiante = %s
          AND asignatura = %s
          AND fecha_solicitud = %s
          AND tema = %s
        LIMIT 1
        """,
        (
            data["codigo_estudiante"],
            data["asignatura"],
            data["fecha_solicitud"],
            data["tema"]
        )
    )
    existe = cur.fetchone() is not None
    cur.close()
    conn.close()
    return existe


def cargar_xsd():
    with open(XSD_PATH, "rb") as f:
        return etree.XMLSchema(etree.parse(f))


XML_SCHEMA = cargar_xsd()


def validar_xml_con_xsd(xml_content: bytes):
    try:
        xml_doc = etree.fromstring(xml_content)
        XML_SCHEMA.assertValid(xml_doc)
        return True, None
    except etree.DocumentInvalid as e:
        return False, str(e)
    except Exception as e:
        return False, f"XML inválido: {str(e)}"


def xml_a_dict(xml_content: bytes) -> dict:
    root = etree.fromstring(xml_content)
    return {
        "codigo_estudiante": root.findtext("codigo_estudiante", default="").strip(),
        "nombre_estudiante": root.findtext("nombre_estudiante", default="").strip(),
        "correo_institucional": root.findtext("correo_institucional", default="").strip(),
        "programa": root.findtext("programa", default="").strip(),
        "asignatura": root.findtext("asignatura", default="").strip(),
        "tema": root.findtext("tema", default="").strip(),
        "descripcion": root.findtext("descripcion", default="").strip(),
        "nivel_urgencia": root.findtext("nivel_urgencia", default="").strip().lower(),
        "fecha_solicitud": root.findtext("fecha_solicitud", default="").strip(),
        "estado": root.findtext("estado", default="").strip().lower()
    }


def dict_a_xml(data: dict, solicitud_id: str) -> bytes:
    root = etree.Element("solicitud_consolidada")
    etree.SubElement(root, "solicitud_id").text = solicitud_id
    for key in [
        "codigo_estudiante", "nombre_estudiante", "correo_institucional", "programa",
        "asignatura", "tema", "descripcion", "nivel_urgencia", "fecha_solicitud", "estado"
    ]:
        etree.SubElement(root, key).text = str(data.get(key, ""))
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")


def parsear_xml_externo(xml_text: str) -> dict:
    root = etree.fromstring(xml_text.encode("utf-8"))
    data = {}
    for child in root:
        if len(child) == 0:
            data[child.tag] = (child.text or "").strip()
        else:
            data[child.tag] = [
                (item.text or "").strip() for item in child
            ]
    return data


def clasificar_solicitud(data: dict) -> str:
    descripcion = data["descripcion"].lower()
    tema = data["tema"].lower()
    compleja = (
        data["nivel_urgencia"] == "alta"
        or len(data["descripcion"]) > 180
        or any(p in descripcion or p in tema for p in [
            "proyecto", "parcial", "examen", "sustentación", "sustentacion", "varios", "muchas dudas"
        ])
    )
    return "compleja" if compleja else "simple"


def validar_calidad(data: dict, contexto: dict | None = None) -> list[dict]:
    errores = []

    if not data.get("codigo_estudiante"):
        errores.append({
            "regla": "codigo_obligatorio",
            "campo": "codigo_estudiante",
            "mensaje": "El código de estudiante es obligatorio",
            "valor_detectado": data.get("codigo_estudiante", "")
        })

    correo = data.get("correo_institucional", "")
    if not correo.endswith("@cecar.edu.co"):
        errores.append({
            "regla": "correo_institucional_valido",
            "campo": "correo_institucional",
            "mensaje": "El correo debe ser institucional @cecar.edu.co",
            "valor_detectado": correo
        })

    try:
        datetime.strptime(data.get("fecha_solicitud", ""), "%Y-%m-%d")
    except ValueError:
        errores.append({
            "regla": "fecha_valida",
            "campo": "fecha_solicitud",
            "mensaje": "La fecha de solicitud debe tener formato YYYY-MM-DD",
            "valor_detectado": data.get("fecha_solicitud", "")
        })

    if data.get("programa") not in PROGRAMAS_VALIDOS:
        errores.append({
            "regla": "programa_existente",
            "campo": "programa",
            "mensaje": "El programa académico no se encuentra en el catálogo permitido",
            "valor_detectado": data.get("programa", "")
        })

    if data.get("estado") not in ESTADOS_VALIDOS:
        errores.append({
            "regla": "consistencia_estado",
            "campo": "estado",
            "mensaje": "El estado de la solicitud no es válido",
            "valor_detectado": data.get("estado", "")
        })

    if data.get("nivel_urgencia") not in URGENCIAS_VALIDAS:
        errores.append({
            "regla": "urgencia_valida",
            "campo": "nivel_urgencia",
            "mensaje": "El nivel de urgencia debe ser baja, media o alta",
            "valor_detectado": data.get("nivel_urgencia", "")
        })

    if es_duplicada(data):
        errores.append({
            "regla": "duplicidad_registro",
            "campo": "tema",
            "mensaje": "Ya existe una solicitud con el mismo estudiante, asignatura, tema y fecha",
            "valor_detectado": data.get("tema", "")
        })

    campos_requeridos = [
        "codigo_estudiante", "nombre_estudiante", "correo_institucional",
        "programa", "asignatura", "tema", "descripcion", "nivel_urgencia", "fecha_solicitud", "estado"
    ]
    faltantes = [campo for campo in campos_requeridos if not data.get(campo)]
    if faltantes:
        errores.append({
            "regla": "completitud_datos",
            "campo": ", ".join(faltantes),
            "mensaje": "Existen campos obligatorios vacíos",
            "valor_detectado": faltantes
        })

    if contexto:
        academico = contexto.get("academico", {})
        gestion = contexto.get("gestion_estudiantil", {})

        if academico.get("programa") and academico.get("programa") != data.get("programa"):
            errores.append({
                "regla": "integridad_estudiante_programa",
                "campo": "programa",
                "mensaje": "El programa informado no coincide con el sistema académico",
                "valor_detectado": data.get("programa", "")
            })

        if gestion.get("correo_institucional") and gestion.get("correo_institucional") != data.get("correo_institucional"):
            errores.append({
                "regla": "consistencia_correo",
                "campo": "correo_institucional",
                "mensaje": "El correo no coincide con el sistema de gestión estudiantil",
                "valor_detectado": data.get("correo_institucional", "")
            })

    return errores


def consultar_sistemas_externos(data: dict) -> dict:
    codigo = data["codigo_estudiante"]
    asignatura = data["asignatura"]

    academico_resp = requests.get(f"{ACADEMICO_URL}/{codigo}", timeout=15)
    gestion_resp = requests.get(f"{GESTION_URL}/{codigo}", timeout=15)
    tutorias_resp = requests.get(f"{TUTORIAS_URL}/{asignatura}", timeout=15)
    bienestar_resp = requests.get(f"{BIENESTAR_URL}/{codigo}", timeout=15)

    academico_resp.raise_for_status()
    gestion_resp.raise_for_status()
    tutorias_resp.raise_for_status()
    bienestar_resp.raise_for_status()

    return {
        "academico": parsear_xml_externo(academico_resp.text),
        "gestion_estudiantil": parsear_xml_externo(gestion_resp.text),
        "tutorias": tutorias_resp.json(),
        "bienestar": bienestar_resp.json()
    }


def procesar_solicitud(data: dict, input_format: str):
    solicitud_id = generar_codigo("INT")
    registrar_evento(solicitud_id, "solicitud_recibida", {"input_format": input_format, "data": data})

    if input_format == "xml":
        registrar_evento(solicitud_id, "transformacion_xml_json", {"detalle": "XML transformado a JSON interno"})

    contexto = consultar_sistemas_externos(data)
    errores = validar_calidad(data, contexto)

    if errores:
        registrar_errores(solicitud_id, errores)
        registrar_evento(solicitud_id, "errores_calidad_detectados", {"errores": errores})
        return {
            "ok": False,
            "solicitud_id": solicitud_id,
            "mensaje": "Se detectaron errores de calidad en la solicitud",
            "errores": errores,
            "contexto_consultado": contexto
        }, 422

    clasificacion = clasificar_solicitud(data)
    consolidado = {
        "solicitud_id": solicitud_id,
        "clasificacion": clasificacion,
        "academico": contexto["academico"],
        "gestion_estudiantil": contexto["gestion_estudiantil"],
        "tutorias": contexto["tutorias"],
        "bienestar": contexto["bienestar"],
        "fecha_procesamiento": ahora_iso()
    }

    guardar_solicitud(solicitud_id, input_format, data, consolidado)
    registrar_evento(solicitud_id, "solicitud_validada", {"clasificacion": clasificacion})
    registrar_evento(solicitud_id, "respuesta_consolidada", consolidado)

    return {
        "ok": True,
        "solicitud_id": solicitud_id,
        "input_format": input_format,
        "data_normalizada": data,
        "respuesta_consolidada": consolidado
    }, 201


@app.get("/")
def home():
    return jsonify({
        "servicio": "Middleware Central CECAR - Corte 2",
        "estado": "ok",
        "base_datos_configurada": bool(DATABASE_URL),
        "endpoints": [
            "POST /api/v2/integracion/xml",
            "POST /api/v2/integracion/json",
            "GET /api/v2/solicitudes/<solicitud_id>",
            "GET /api/v2/solicitudes/<solicitud_id>/xml",
            "GET /api/v2/eventos",
            "GET /api/v2/errores-calidad"
        ]
    })


@app.post("/api/v2/integracion/xml")
def integrar_xml():
    if not validar_api_key():
        return jsonify({"ok": False, "mensaje": "X-API-key inválida"}), 401

    xml_content = request.data
    if not xml_content:
        return jsonify({"ok": False, "mensaje": "Debe enviar un XML en el body"}), 400

    valido, error = validar_xml_con_xsd(xml_content)
    if not valido:
        return jsonify({
            "ok": False,
            "mensaje": "El XML no cumple la estructura XSD",
            "detalle": error
        }), 400

    data = xml_a_dict(xml_content)
    respuesta, status = procesar_solicitud(data, "xml")
    return jsonify(respuesta), status


@app.post("/api/v2/integracion/json")
def integrar_json():
    if not validar_api_key():
        return jsonify({"ok": False, "mensaje": "X-API-key inválida"}), 401

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"ok": False, "mensaje": "Debe enviar un JSON válido"}), 400

    respuesta, status = procesar_solicitud(data, "json")
    return jsonify(respuesta), status


@app.get("/api/v2/solicitudes/<solicitud_id>")
def obtener_solicitud(solicitud_id):
    if not validar_api_key():
        return jsonify({"ok": False, "mensaje": "X-API-key inválida"}), 401

    solicitud = obtener_solicitud_db(solicitud_id)
    if not solicitud:
        return jsonify({"ok": False, "mensaje": "Solicitud no encontrada"}), 404

    return jsonify({"ok": True, "solicitud": solicitud})


@app.get("/api/v2/solicitudes/<solicitud_id>/xml")
def exportar_solicitud_xml(solicitud_id):
    if not validar_api_key():
        return jsonify({"ok": False, "mensaje": "X-API-key inválida"}), 401

    solicitud = obtener_solicitud_db(solicitud_id)
    if not solicitud:
        return jsonify({"ok": False, "mensaje": "Solicitud no encontrada"}), 404

    data = {
        "codigo_estudiante": solicitud["codigo_estudiante"],
        "nombre_estudiante": solicitud["nombre_estudiante"],
        "correo_institucional": solicitud["correo_institucional"],
        "programa": solicitud["programa"],
        "asignatura": solicitud["asignatura"],
        "tema": solicitud["tema"],
        "descripcion": solicitud["descripcion"],
        "nivel_urgencia": solicitud["nivel_urgencia"],
        "fecha_solicitud": str(solicitud["fecha_solicitud"]),
        "estado": solicitud["estado"]
    }
    xml_bytes = dict_a_xml(data, solicitud_id)
    return Response(xml_bytes, mimetype="application/xml")


@app.get("/api/v2/eventos")
def listar_eventos():
    if not validar_api_key():
        return jsonify({"ok": False, "mensaje": "X-API-key inválida"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM eventos ORDER BY created_at DESC LIMIT 200")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "total": len(rows), "eventos": rows})


@app.get("/api/v2/errores-calidad")
def listar_errores():
    if not validar_api_key():
        return jsonify({"ok": False, "mensaje": "X-API-key inválida"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM errores_calidad ORDER BY created_at DESC LIMIT 200")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "total": len(rows), "errores": rows})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
