import json


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError(f"Non-JSON constant: {value}")


def strict_json_loads(text: str):
    return json.loads(
        text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )
