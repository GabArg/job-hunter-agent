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

La navegación diaria se divide en `Job Hunt`, `Seguimiento`, `Analytics`, `Knowledge Base` y `System / Runs`.
La decisión del scorer (`APPLY/REVIEW/REJECT`) se mantiene separada del seguimiento
operativo (`NEW`, `SHORTLISTED`, `CV_GENERATED`, `APPROVED_TO_APPLY`, `APPLIED`, `SKIPPED`).

## Application Tracking & Analytics

El flujo completo es `Discovery → Evaluate → CV → Apply manually → Track → Analyze`.
`application_status` conserva el workflow operativo, mientras `application_stage` registra el proceso
de selección (`APPLIED`, contactos, entrevistas, assessment, oferta y cierres). Una postulación,
respuesta o entrevista sólo se registra por una acción humana explícita. Generar un CV, abrir un
link, aprobar un email, crear un borrador o enviarlo no altera el tracking.

Cada cambio agrega un evento a `application_stage_history`; las correcciones también son eventos y
no borran la historia. El dashboard permite guardar una nota local y una próxima acción. No deben
guardarse secretos ni datos sensibles en las notas.

La vista `Seguimiento` muestra procesos activos/cerrados, días en etapa, próximas acciones y filtros.
`Analytics` ofrece KPIs, tasas de respuesta/entrevista/oferta/contratación, funnel, series diarias y
semanales, tiempos de respuesta y performance descriptiva por rol, fuente, canal y score. Estas
métricas nunca modifican scoring, decisiones ni el perfil.

```powershell
job-hunter tracking-summary
job-hunter set-stage 123 HR_INTERVIEW --note "Entrevista ficticia"
job-hunter application-history 123
```

### Discovery automático en Windows

El runner detecta la raíz, activa `.venv` cuando existe, usa el lock de discovery y
escribe logs en `logs/discovery/`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_discovery.ps1 -Slot manual
```

La instalación de las tareas de las 08:00 y 18:00 es explícita y manual:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows_tasks.ps1
```

El instalador crea `JobHunter-Morning` y `JobHunter-Evening` con hora local,
`StartWhenAvailable` y una sola instancia. No se ejecuta desde la aplicación ni los tests.

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

## CV Agent

Crear las copias privadas, que están ignoradas por Git:

```powershell
New-Item -ItemType Directory -Force private
Copy-Item config/candidate_profile.example.yaml private/candidate_profile.yaml
Copy-Item config/master_cv.example.yaml private/master_cv.yaml
```

Generar un CV para una oferta `APPLY` o `REVIEW` almacenada en SQLite:

```powershell
python -m job_hunter.cli cv --job-id 123 --master-cv private/master_cv.yaml --output outputs/
python -m job_hunter.cli cv --url https://jobs.example/job --master-cv private/master_cv.yaml
python -m job_hunter.cli generate-cv 123 --master-cv private/master_cv.yaml
```

El motor determinístico selecciona hechos del CV maestro y conserva
`source_fact_ids` auditables para cada bullet. El validator bloquea bullets sin
evidencia, empresas o tecnologías ausentes del maestro. El HTML se conserva como
preview/debug y `generate-cv` produce el formato principal de entrega:

```text
outputs/cvs/<job-id>/Guido_Broccoli_CV_<Role>_<Company>.html
outputs/cvs/<job-id>/Guido_Broccoli_CV_<Role>_<Company>.pdf
```

### PDF ATS-friendly

El backend local usa ReportLab para composición A4 de texto seleccionable y `pypdf`
para validar páginas, contenido y contactos. Ambas dependencias se instalan con
`pip install -e .`; no se utiliza navegador, API ni servicio externo. El renderer
parte del mismo `AdaptedCV` ya validado y nunca genera hechos ni reescribe el resumen.

Se intenta el layout normal, luego espaciado compacto y finalmente una reducción
segura de bloques secundarios ya priorizados por el adapter. Nunca baja de 9.5 pt.
Si todavía supera dos páginas queda en estado `TOO_LONG` y no se habilita para email.

En Windows, si la generación falla, verificar que el entorno virtual esté activo y
reinstalar las dependencias puras de Python:

```powershell
python -m pip install --upgrade reportlab pypdf
python -m job_hunter.cli generate-cv 123
```

El dashboard permite elegir el CSV, el perfil y la base de datos desde la barra lateral, ejecutar el pipeline y filtrar los resultados.

## Tests

```powershell
pytest
```

## Canales de postulación y Gmail

El detector distingue `LINK`, `EMAIL`, `LINK_EMAIL` y `UNKNOWN`. Los emails siguen
el flujo obligatorio `GENERATED → APPROVED → SENT`; abrir un link nunca marca una
oferta como postulada. Gmail está preparado como límite OAuth, pero permanece
inactivo hasta una configuración explícita. No se usa contraseña ni SMTP simple.

Los futuros archivos OAuth deben guardarse únicamente en:

```text
private/gmail/client_secret.json
private/gmail/token.json
```

Todo `private/` está ignorado por Git. La aplicación nunca activa Gmail ni envía
emails automáticamente durante discovery, tests o generación de CV.

### Conectar Gmail mediante OAuth 2.0

Job Hunter Agent solicita únicamente el scope oficial
`https://www.googleapis.com/auth/gmail.compose`. En Fase 5.1 puede crear borradores,
pero el envío real permanece bloqueado.

1. Entrar a Google Cloud Console y crear o seleccionar un proyecto.
2. Habilitar **Gmail API** para ese proyecto.
3. Configurar **OAuth consent screen** con los datos requeridos por Google.
4. Crear un **OAuth Client ID** de tipo **Desktop App**.
5. Descargar el JSON de credenciales.
6. Guardarlo localmente como `private/gmail/client_secret.json`.
7. Usar **Conectar Gmail** en `System / Runs`, o ejecutar:

```powershell
python -m job_hunter.cli gmail-connect
python -m job_hunter.cli gmail-status
```

8. Autorizar explícitamente la cuenta en el navegador abierto por Google.
9. El token se guardará sólo en `private/gmail/token.json` y se reutilizará o
   refrescará mediante las librerías oficiales.

La contraseña nunca pasa por Job Hunter Agent. Los tokens, client secret y datos
OAuth quedan dentro de `private/`, ignorado por Git, y nunca se almacenan en SQLite.
Revocar el acceso desde la cuenta de Google invalida la conexión local. El dashboard
no inicia OAuth por sí solo y crear un borrador no marca la vacante como postulada.

## Formato de entrada

El CSV acepta las columnas `title`, `company`, `location`, `work_mode`, `description`, `source` y `url`. La URL es obligatoria y se usa como clave única de deduplicación.

## Decisiones

- `APPLY`: score mayor o igual a 75.
- `REVIEW`: score entre 55 y 74.99.
- `REJECT`: score menor a 55 o cualquier regla de rechazo duro.

El resultado también incluye habilidades coincidentes/faltantes y motivos positivos o de rechazo, de modo que cada decisión sea auditable.
