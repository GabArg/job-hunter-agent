# Job Hunter Agent

V1 local para importar ofertas laborales desde CSV, normalizarlas, deduplicarlas por URL, evaluarlas contra un perfil configurable y clasificarlas como `APPLY`, `REVIEW` o `REJECT`.

Esta versión **no automatiza postulaciones**. Todo el procesamiento y almacenamiento ocurre localmente.

## Requisitos

- Python 3.11+
- SQLite (incluido con Python)

## Instalación

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Configuración segura

Copiar el perfil de ejemplo y personalizar la copia local:

```powershell
Copy-Item config/profile.example.yaml config/profile.yaml
```

`config/profile.yaml` está ignorado por Git. No incluir datos personales reales en archivos versionados.

## Uso

Ejecutar el pipeline de muestra:

```powershell
job-hunter run --input data/sample_jobs.csv --profile config/profile.example.yaml --database data/jobs.db
```

Levantar el dashboard:

```powershell
streamlit run app/streamlit_app.py
```

El dashboard permite elegir el CSV, el perfil y la base de datos desde la barra lateral, ejecutar el pipeline y filtrar los resultados.

## Tests

```powershell
pytest
```

## Formato de entrada

El CSV acepta las columnas `title`, `company`, `location`, `work_mode`, `description`, `source` y `url`. La URL es obligatoria y se usa como clave única de deduplicación.

## Decisiones

- `APPLY`: score mayor o igual a 75.
- `REVIEW`: score entre 55 y 74.99.
- `REJECT`: score menor a 55 o cualquier regla de rechazo duro.

El resultado también incluye habilidades coincidentes/faltantes y motivos positivos o de rechazo, de modo que cada decisión sea auditable.
