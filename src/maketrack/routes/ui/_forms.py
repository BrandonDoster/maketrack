def strip_empty_strings(form: dict) -> dict:
    """Drop empty-string form values so Pydantic uses defaults instead of
    failing to coerce '' into a number / typed field. Use on CREATE routes
    where missing == 'use schema default'."""
    return {k: v for k, v in form.items() if not (isinstance(v, str) and v.strip() == "")}


def null_empty_strings(form: dict) -> dict:
    """For UPDATE routes: keep every key, but turn empty/whitespace strings
    into None so the PATCH payload says 'clear this field' rather than
    'leave it alone'. Otherwise Pydantic's exclude_unset semantics treat
    a stripped key as no-change, and the user can't clear text fields.
    """
    out: dict = {}
    for k, v in form.items():
        if isinstance(v, str):
            stripped = v.strip()
            out[k] = stripped if stripped else None
        else:
            out[k] = v
    return out


def format_validation_error(err: dict) -> str:
    field = ".".join(str(p) for p in err.get("loc", []))
    msg = err.get("msg", "invalid")
    return f"{field}: {msg}" if field else msg
