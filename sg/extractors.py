"""Extractors fill a gate's fields as cited facts: {field, value, file, page, quote}.
Every adapter returns the same shape, so the rest of the pipeline never changes."""
from .llm import call_claude_tool


def claude_extractor(gate, room, pages):
    fields = gate["extractor"]["fields"]
    schema = {"type": "object", "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {"field": {"type": "string"}, "value": {"type": "string"},
                       "file": {"type": "string"}, "page": {"type": "integer"},
                       "quote": {"type": "string"}},
        "required": ["field", "value", "file", "page", "quote"]}}}, "required": ["facts"]}
    docs = "\n\n".join(f"[file: {p['file']} | page: {p['page']}"
                         + (f" | section: {p['section']}" if p.get("section") else "") + f"]\n{p['text']}"
                         for p in pages)
    field_list = "\n".join(f"- {f['name']}: {f.get('description', '')}" for f in fields)
    system = ("You extract facts from fund documents. Copy, never infer. For each field you can "
              "support, return the value and a VERBATIM quote from the page, with the exact file "
              "and page. If a field is not stated, omit it. " + gate["extractor"].get("rules", ""))
    out = call_claude_tool(system, f"Fields:\n{field_list}\n\nDocuments:\n{docs}",
                           "record_facts", schema)
    return out["facts"]


EXTRACTORS = {"claude": claude_extractor}
