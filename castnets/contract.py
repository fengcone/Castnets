"""Generate response schemas from the same dataclasses used by the service."""
import json
import types
from dataclasses import fields, is_dataclass
from typing import Literal, Union, get_args, get_origin, get_type_hints

from . import models


def type_schema(kind):
    origin, args = get_origin(kind), get_args(kind)
    if origin is Literal:
        return {"type": "string", "enum": list(args)}
    if origin is list:
        return {"type": "array", "items": type_schema(args[0])}
    if origin in (types.UnionType, Union):
        return {"anyOf": [type_schema(arg) for arg in args]}
    if is_dataclass(kind):
        return {"$ref": f"#/components/schemas/{kind.__name__}"}
    return {"type": {str: "string", int: "integer", bool: "boolean", type(None): "null"}[kind]}


def object_schema(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


def openapi():
    schemas = {}
    for name in ("Source", "Segment", "Podcast", "Episode", "Content", "Context", "Answer", "Turn", "Branch"):
        cls = getattr(models, name)
        hints = get_type_hints(cls)
        schemas[name] = object_schema({f.name: type_schema(hints[f.name]) for f in fields(cls)})
    question = {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"\S"}
    schemas["CreateBranch"] = object_schema({
        "episode_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "anchor_ms": {"type": "integer", "minimum": 0, "maximum": 86400000},
        "question": question,
        "resume_offset_ms": {"type": "integer", "minimum": 0, "maximum": 30000, "default": 5000},
    }, ["episode_id", "anchor_ms", "question"])
    schemas["CreateTurn"] = object_schema({"question": question})
    schemas["Error"] = object_schema({"error": object_schema({"code": {"type": "string"}, "message": {"type": "string"}})})
    paths = {}

    def operation(path, method, response, request=None, status="200", description=""):
        spec = {"summary": description, "responses": {
            status: {"description": "Success", "content": {"application/json": {"schema": response}}},
            **{code: {"description": message, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
               for code, message in {"400": "Invalid request", "404": "Not found", "409": "Closed branch", "413": "Body too large", "415": "JSON required"}.items()}}}
        if request:
            spec["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{request}"}}}}
        if "{id}" in path:
            spec["parameters"] = [{"in": "path", "name": "id", "required": True, "schema": {"type": "string"}}]
        paths.setdefault(path, {})[method] = spec

    ref = lambda name: {"$ref": f"#/components/schemas/{name}"}
    operation("/health", "get", object_schema({"status": {"type": "string"}, "mode": {"type": "string"}}), description="Local server health")
    operation("/v1/podcasts", "get", {"type": "array", "items": ref("Podcast")}, description="Imported podcast feeds")
    operation("/v1/podcasts/{id}", "get", ref("Podcast"), description="Selected podcast feed")
    operation("/v1/podcasts/{id}/episodes", "get", {"type": "array", "items": ref("Episode")}, description="Episodes in selected podcast")
    operation("/v1/episodes", "get", {"type": "array", "items": ref("Episode")}, description="Imported episodes, RSS order")
    operation("/v1/episodes/{id}", "get", ref("Episode"), description="Episode and chapters")
    operation("/v1/episodes/{id}/content", "get", ref("Content"), description="Imported transcript or chapters-only content")
    operation("/v1/branches", "get", {"type": "array", "items": ref("Branch")}, description="Saved branches")
    operation("/v1/branches", "post", ref("Branch"), "CreateBranch", "201", "Pause anchor and first question; retry creates another branch")
    operation("/v1/branches/{id}", "get", ref("Branch"), description="Branch and immutable turn snapshots")
    operation("/v1/branches/{id}/turns", "post", ref("Branch"), "CreateTurn", "201", "Append question while active; no retry deduplication")
    operation("/v1/branches/{id}/resume", "post", ref("Branch"), description="Idempotently close branch and return resume position; send no body")
    return {"openapi": "3.1.0", "info": {"title": "Castnets M0", "version": "1.0.0"},
            "servers": [{"url": "http://127.0.0.1:8765"}], "paths": paths, "components": {"schemas": schemas}}


if __name__ == "__main__":
    print(json.dumps(openapi(), ensure_ascii=False, indent=2))
