# Screenshot publication checklist

This directory contains reviewed, public-safe screenshots captured from the real Streamlit application.

Published filenames:

- `dashboard.png`
- `job-detail.png`
- `tracking-analytics.png`

Publication checks:

- use public-safe job data or a clearly labeled fictional temporary dataset;
- remove email addresses, recruiter names, notes, IDs, and local filesystem paths;
- confirm that no OAuth, token, or private profile data is visible;
- capture the current UI at a readable desktop resolution;
- add the image to the main README only after the PNG exists and has been reviewed.

`dashboard.png` and `job-detail.png` use the local application database. `tracking-analytics.png` uses a temporary fictional SQLite database because the real database has no application-tracking rows. The temporary data is identified inside the screenshot and was never inserted into `data/jobs.db`.
