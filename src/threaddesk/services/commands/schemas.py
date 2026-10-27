"""Small source-owned schema constructors for public command declarations."""
ID = {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"}
TEXT = {"type": "string", "maxLength": 10000}
BOOL = {"type": "boolean"}
REV = {"type": "integer", "minimum": 0}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100}
OFFSET = {"type": "integer", "minimum": 0, "maximum": 100000}
PAGE = {"limit": LIMIT, "offset": OFFSET}


def obj(properties=None, required=()):
    return {"type": "object", "additionalProperties": False,
            "properties": properties or {}, "required": list(required)}


def choice(*values):
    return {"type": "string", "enum": list(values)}


def array(items, maximum=100):
    return {"type": "array", "items": items, "maxItems": maximum}


def page(rows, args, *, name="items"):
    offset, limit = args.get("offset", 0), args.get("limit", 50)
    end = offset + limit
    return {name: rows[offset:end], "total": len(rows),
            "next_offset": end if end < len(rows) else None}
