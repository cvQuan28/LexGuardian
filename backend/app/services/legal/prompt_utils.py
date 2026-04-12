"""
Safe prompt assembly for legal workflows.

`str.format` / `str.format_map` treat `{...}` in injected document text as
placeholders and raise KeyError. Use positional replacement for known keys only.
"""


def fill_prompt_placeholders(template: str, **kwargs: str) -> str:
    out = template
    for key, value in kwargs.items():
        out = out.replace("{" + key + "}", value)
    return out
