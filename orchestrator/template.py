from pathlib import Path
from typing import TYPE_CHECKING, Set
import re


PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
VALID_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class TemplateError(ValueError):
    pass


class TemplateLoader:
    """
    Reads the Physics template as plain text and extracts placeholder names.
    """

    def __init__(self, template_path: str | Path):
        self.template_path = Path(template_path)
        self.text: str = ""
        self.placeholders: Set[str] = set()

    def load(self) -> "TemplateLoader":
        if not self.template_path.exists():
            raise TemplateError(f"template file not found: {self.template_path}")

        self.text = self.template_path.read_text(encoding="utf-8")
        self.placeholders = self.extract_placeholders(self.text)
        return self

    @staticmethod
    def extract_placeholders(text: str) -> Set[str]:
        placeholders: Set[str] = set()
        for match in PLACEHOLDER_RE.finditer(text):
            placeholders.add(match.group(1))

        # Catch malformed placeholder-like text such as {{bad_name}} or {{NAME-1}}
        malformed = re.findall(r"\{\{([^}]+)\}\}", text)
        for token in malformed:
            if not VALID_NAME_RE.match(token):
                raise TemplateError(
                    f"invalid placeholder {token!r}; must match {VALID_NAME_RE.pattern}"
                )

        return placeholders

    def validate(
        self,
        config: "ControlConfig",
        reserved_placeholders: Set[str] | None = None,
    ) -> None:
        config.validate_against_template(
            self.placeholders,
            reserved_placeholders=reserved_placeholders,
        )


if TYPE_CHECKING:
    from .config import ControlConfig
