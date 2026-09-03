"""Helpers for preserving task-language annotations on captured episodes."""

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
from typing import Mapping


_TASK_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_TASK_ID_SEPARATOR_PATTERN = re.compile(r"[\s_]+")
_SUGGESTED_TASK_ID_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_PLACEHOLDER_ENGLISH_PATTERN = re.compile(
    r"(?:test|task|demo|unknown|none|n/?a|episode)(?:[\s_-]*\d+)?\Z",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CaptureTaskAnnotation:
    """Task label captured with a single collection session."""

    task_name: str
    task_id: str
    language_instruction_en: str
    language_instruction_zh: str
    annotation_source: str = "capture_ui"

    def as_dict(self) -> dict:
        """Return the serializable episode metadata representation."""
        return asdict(self)


def normalize_task_id(value: object) -> str:
    """Return a lower-case, ASCII hyphenated task identifier.

    Whitespace and underscores are accepted as word separators. Other
    non-identifier characters are rejected so a supplied label cannot silently
    become a different task.
    """
    text = _collapse_whitespace(value)
    if not text:
        return ""
    if not text.isascii():
        raise ValueError("task_id must use ASCII letters, digits, and hyphens")
    normalized = _TASK_ID_SEPARATOR_PATTERN.sub("-", text.lower())
    if not _TASK_ID_PATTERN.fullmatch(normalized):
        raise ValueError("task_id must use ASCII letters, digits, and hyphens")
    return normalized


def suggest_task_id(english_instruction: str) -> str:
    """Suggest a stable slug from the supplied English instruction."""
    text = _collapse_whitespace(english_instruction).lower()
    return "-".join(_SUGGESTED_TASK_ID_TOKEN_PATTERN.findall(text))


def parse_capture_task_annotation(
    *, task_name: str, task_id: object, english: object, chinese: object
) -> dict:
    """Build episode annotation metadata from capture parameters.

    Empty language fields are intentionally retained: ACT collection does not
    require language, while downstream VLA validation can enforce it later.
    """
    supplied_task_id = _collapse_whitespace(task_id)
    language_instruction_en = _collapse_whitespace(english)
    language_instruction_zh = _collapse_whitespace(chinese)
    if not (supplied_task_id or language_instruction_en or language_instruction_zh):
        return {}
    annotation = CaptureTaskAnnotation(
        task_name=str(task_name),
        task_id=(
            normalize_task_id(supplied_task_id)
            if supplied_task_id
            else suggest_task_id(language_instruction_en)
        ),
        language_instruction_en=language_instruction_en,
        language_instruction_zh=language_instruction_zh,
    )
    return annotation.as_dict()


def load_task_catalog(path: Path) -> list[dict]:
    """Return one most-recent valid task label for each task ID.

    Catalog rows are append-only usage events. Invalid or malformed historical
    rows are ignored so a partial write cannot prevent label selection.
    """
    latest_by_task_id: dict[str, tuple[float, int, dict]] = {}
    try:
        stream = Path(path).open("r", encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    with stream:
        for sequence, line in enumerate(stream):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            catalog_row = _catalog_row(row)
            if catalog_row is None:
                continue
            task_id = catalog_row["task_id"]
            candidate = (catalog_row["last_used_at"], sequence, catalog_row)
            existing = latest_by_task_id.get(task_id)
            if existing is None or candidate[:2] >= existing[:2]:
                latest_by_task_id[task_id] = candidate
    return [
        item[2]
        for item in sorted(
            latest_by_task_id.values(),
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
    ]


def register_task_label(path: Path, annotation: Mapping[str, object], now: float) -> dict:
    """Append a task-label use event, rejecting contradictory task-language text."""
    label = _catalog_annotation(annotation)
    task_id = label["task_id"]
    if not task_id:
        raise ValueError("task_id is required to register a task label")

    existing = next(
        (row for row in load_task_catalog(path) if row["task_id"] == task_id),
        None,
    )
    if existing is not None:
        for field, description in (
            ("language_instruction_en", "English"),
            ("language_instruction_zh", "Chinese"),
        ):
            if label[field] and existing[field] and label[field] != existing[field]:
                raise ValueError(
                    f"task ID {task_id!r} has conflicting {description} instruction"
                )
            if not label[field]:
                label[field] = existing[field]

    try:
        last_used_at = float(now)
    except (TypeError, ValueError) as exc:
        raise ValueError("task-label timestamp must be finite") from exc
    if not math.isfinite(last_used_at):
        raise ValueError("task-label timestamp must be finite")
    catalog_row = {**label, "last_used_at": last_used_at}
    catalog_path = Path(path)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with catalog_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(catalog_row, ensure_ascii=False) + "\n")
    return catalog_row


def validate_vla_english_instruction(value: object) -> str | None:
    """Return a VLA rejection reason for blank or placeholder English text."""
    text = _collapse_whitespace(value)
    if not text or not re.search(r"[A-Za-z]", text):
        return "missing_english_instruction"
    if _PLACEHOLDER_ENGLISH_PATTERN.fullmatch(text):
        return "invalid_english_instruction"
    return None


def _catalog_row(value: object) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    try:
        label = _catalog_annotation(value)
        last_used_at = float(value.get("last_used_at"))
    except (TypeError, ValueError):
        return None
    if not label["task_id"] or not math.isfinite(last_used_at):
        return None
    return {**label, "last_used_at": last_used_at}


def _catalog_annotation(annotation: Mapping[str, object]) -> dict:
    return {
        "task_name": str(annotation.get("task_name", "")),
        "task_id": normalize_task_id(annotation.get("task_id", "")),
        "language_instruction_en": _collapse_whitespace(
            annotation.get("language_instruction_en", "")
        ),
        "language_instruction_zh": _collapse_whitespace(
            annotation.get("language_instruction_zh", "")
        ),
        "annotation_source": str(annotation.get("annotation_source", "capture_ui")),
    }


def _collapse_whitespace(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())
