"""Branding stored on a company. The admin app and the customer portal read it."""

from __future__ import annotations

from urllib.parse import urlparse

from django.db import connection
from django_tenants.utils import get_public_schema_name

# Same fallbacks the admin app used when branding was baked in at build time.
DEFAULT_COLORS = {
    "primary": "#000000",
    "primaryForeground": "#ffffff",
    "primaryHover": "#808080",
}
_COLOR_KEYS = tuple(DEFAULT_COLORS)
_LOOK_KEYS = {"name", "logo", "favicon", "title", "description", "colors"}


def validate_look(value: object) -> list[str]:
    """Messages for a `look` value. An empty object is valid."""
    if value in (None, {}):
        return []
    if not isinstance(value, dict):
        return ["Look must be an object."]
    return [
        *_unknown(set(value), _LOOK_KEYS, "look"),
        *_string_errors(value),
        *_asset_error("logo", value.get("logo")),
        *_asset_error("favicon", value.get("favicon")),
        *_color_errors(value.get("colors"), present="colors" in value),
    ]


def public_look(*, name: str, look: object) -> dict:
    """The branding a frontend can apply. Missing pieces use the company name."""
    raw = look if isinstance(look, dict) else {}
    display_name = _text(raw.get("name")) or name
    colors = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
    return {
        "name": display_name,
        "logo": _asset(raw.get("logo")),
        "favicon": _asset(raw.get("favicon")),
        "title": _text(raw.get("title")) or display_name,
        "description": _text(raw.get("description")),
        "colors": {
            key: _hex(colors.get(key)) or DEFAULT_COLORS[key] for key in _COLOR_KEYS
        },
    }


def on_public_schema() -> bool:
    return connection.schema_name == get_public_schema_name()


def _unknown(keys: set, allowed: set, label: str) -> list[str]:
    extra = sorted(keys - allowed)
    if not extra:
        return []
    return [f"Unknown {label} keys: {', '.join(extra)}."]


def _string_errors(value: dict) -> list[str]:
    keys = ("name", "logo", "favicon", "title", "description")
    return [
        f"{key} must be a string."
        for key in keys
        if key in value and not isinstance(value[key], str)
    ]


def _color_errors(colors: object, *, present: bool) -> list[str]:
    if not present:
        return []
    if not isinstance(colors, dict):
        return ["colors must be an object."]
    errors = _unknown(set(colors), set(_COLOR_KEYS), "color")
    errors.extend(
        f"colors.{key} must be a hex color, such as #1B4D3E."
        for key in _COLOR_KEYS
        if key in colors and not _hex(colors[key])
    )
    return errors


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _hex(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) not in {4, 7} or not text.startswith("#"):
        return ""
    digits = text[1:]
    if any(char not in "0123456789abcdefABCDEF" for char in digits):
        return ""
    return text


def _asset(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if _asset_error("asset", text):
        return ""
    return text


def _asset_error(label: str, value: object) -> list[str]:
    if value is None or not isinstance(value, str):
        return []
    text = value.strip()
    if text == "":
        return []
    if text.startswith("/") and not text.startswith("//"):
        return []
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return []
    return [f"{label} must be an empty string, a site path, or an http(s) URL."]
