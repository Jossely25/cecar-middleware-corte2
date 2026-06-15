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
);

CREATE TABLE IF NOT EXISTS eventos (
    id SERIAL PRIMARY KEY,
    solicitud_id VARCHAR(30) NOT NULL,
    tipo_evento VARCHAR(80) NOT NULL,
    payload JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS errores_calidad (
    id SERIAL PRIMARY KEY,
    solicitud_id VARCHAR(30) NOT NULL,
    regla VARCHAR(120) NOT NULL,
    campo VARCHAR(80) NOT NULL,
    mensaje TEXT NOT NULL,
    valor_detectado TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
