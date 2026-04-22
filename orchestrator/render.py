from pathlib import Path
from typing import Any, Dict

from .template import TemplateError, TemplateLoader

class Renderer:
    """
    Performs strict placeholder substitution for a single case.
    """

    def __init__(self, template_text: str):
        self.template_text = template_text
        self.placeholders = TemplateLoader.extract_placeholders(template_text)

    def render(self, values: Dict[str, Any]) -> str:
        missing = sorted(self.placeholders - set(values))

        if missing:
            raise TemplateError("missing values for placeholders: " + ", ".join(missing))

        rendered = self.template_text
        for name in sorted(self.placeholders):
            rendered = rendered.replace(f"{{{{{name}}}}}", self._to_text(values[name]))
        return rendered

    @staticmethod
    def _to_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            return format(value, ".15g")
        return str(value)

    @staticmethod
    def build_generated_input_path(
        worker_dir: str | Path,
        case_id: int,
        suffix: str = ".in",
        stem_prefix: str = "input_case_",
    ) -> Path:
        worker_dir = Path(worker_dir)
        return worker_dir / f"{stem_prefix}{case_id:05d}{suffix}"
