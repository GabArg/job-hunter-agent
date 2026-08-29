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

Descubrir ofertas desde APIs públicas (sin login):

```powershell
python -m job_hunter.cli discover --query "Data Analyst" --limit 10
python -m job_hunter.cli discover --source remoteok --query "Business Analyst" --limit 5
python -m job_hunter.cli discover --query-group analytics --max-age-days 14
```

Si no se indica `--query`, se usan todas las `search_queries` del perfil. Las fuentes
fallan de manera aislada, se aplican filtros preliminares de relevancia y luego cada
oferta aceptada pasa por el normalizador, scorer y SQLite. Los adaptadores respetan
los endpoints públicos: no sortean login, CAPTCHA, rate limits ni controles anti-bot.

### Career targets y ATS públicos

`career_targets` permite incorporar empresas sin hardcodearlas. Cada target define
`company`, `ats`, `board_token` y, opcionalmente, `careers_url`. Se soportan los
feeds públicos de `greenhouse`, `lever`, `ashby` y `workable`; `generic` procesa
career pages HTTPS con datos estructurados JSON-LD `JobPosting`.

```yaml
career_targets:
  - company: Example Company
    ats: lever
    board_token: example-company
    careers_url: https://jobs.lever.co/example-company
```

No se envían postulaciones. Si un futuro conector necesita una API key, debe leerla
desde una variable de entorno y nunca desde un archivo versionado.

Discovery separa coincidencia potencial de título de la decisión final. Antes del
scoring descarta publicaciones antiguas y ubicaciones incompatibles, incluyendo
`US only`, `EU only`, `UK only` y `Canada only`. Un `Remote` sin evidencia explícita
de Argentina o LATAM no se considera compatible por defecto.

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
