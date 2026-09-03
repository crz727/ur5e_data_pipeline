"""Helpers for preserving task-language annotations on captured episodes."""

from dataclasses import asdict, dataclass
import re


_TASK_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_TASK_ID_SEPARATOR_PATTERN = re.compile(r"[\s_]+")
_SUGGESTED_TASK_ID_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


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


def _collapse_whitespace(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())
