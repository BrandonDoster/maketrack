def strip_empty_strings(form: dict) -> dict:
    """Drop empty-string form values so Pydantic uses defaults instead of
    failing to coerce '' into a number / typed field."""
    return {k: v for k, v in form.items() if not (isinstance(v, str) and v.strip() == "")}


def format_validation_error(err: dict) -> str:
    field = ".".join(str(p) for p in err.get("loc", []))
    msg = err.get("msg", "invalid")
    return f"{field}: {msg}" if field else msg
