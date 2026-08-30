from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .models import AdaptedCV
from .renderer import dynamic_professional_title


MAX_CV_FILENAME_LENGTH = 120


def professional_cv_stem(cv: AdaptedCV, max_length: int = MAX_CV_FILENAME_LENGTH - 5) -> str:
    """Build a deterministic, Windows-safe CV basename from factual/job data."""
    name_parts = cv.personal.get("name", "").split()
    candidate = "_".join(part for part in (name_parts[:1] + name_parts[-1:]) if part) or "Candidate"
    prefix = f"{_component(candidate)}_CV_"
    company = _component(cv.company) or "Company"
    role = _component(dynamic_professional_title(cv)) or "Role"
    available = max(24, max_length - len(prefix) - 1)
    role_limit = max(12, available * 3 // 5)
    role = role[:role_limit].rstrip("_")
    company = company[: max(10, available - len(role) - 1)].rstrip("_")
    return f"{prefix}{role}_{company}"[:max_length].rstrip("_")


def professional_cv_paths(output_dir: str | Path, cv: AdaptedCV) -> tuple[Path, Path]:
    stem = professional_cv_stem(cv)
    directory = Path(output_dir)
    return directory / f"{stem}.pdf", directory / f"{stem}.html"


def is_professional_cv_filename(path: str | Path) -> bool:
    name = Path(path).name
    return (
        name.lower().endswith(".pdf")
        and len(name) <= MAX_CV_FILENAME_LENGTH
        and re.fullmatch(r"[A-Za-z0-9_]+\.pdf", name) is not None
        and "_CV_" in name
    )


def _component(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", ascii_value)).strip("_")
