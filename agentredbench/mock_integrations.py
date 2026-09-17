"""Generic, data-driven mock integration engine for the harness.

MockEnv builds its tool surface from the connector registry (connectors.py) and
its state from a scenario's `seed_state` (a dict of collection name -> list of
records). It dispatches tool calls by the spec's `kind`, so a new scenario or
connector needs no engine change — this is what lets attacks be diversified
from YAML alone.

Observable side-effects the grader looks at:
  - self.outbox : messages the agent sent (email / chat), each with a
                  `destination` list and a `body`
  - self.writes : record fields the agent updated/created
  - self.calls  : every tool call with a deep-copied result snapshot
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from connectors import tool_specs


def _searchable_text(record: dict[str, Any]) -> str:
    return " ".join(str(v) for v in record.values() if isinstance(v, (str, int, float))).lower()


class MockEnv:
    def __init__(self, connectors: list[str], seed_state: dict[str, Any]):
        self.specs = tool_specs(connectors)
        self.tools = {s["name"]: s for s in self.specs}
        self.state: dict[str, list[dict[str, Any]]] = copy.deepcopy(seed_state or {})
        self.state.setdefault("_config", {})  # non-list config bag, e.g. user email
        self.calls: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []

    # ---- helpers -------------------------------------------------------------
    def _collection(self, name: str) -> list[dict[str, Any]]:
        col = self.state.setdefault(name, [])
        if not isinstance(col, list):
            raise TypeError(f"collection {name!r} is not a list")
        return col

    def _find(self, collection: str, rec_id: str) -> dict[str, Any] | None:
        for r in self._collection(collection):
            if r.get("id") == rec_id:
                return r
        return None

    # ---- injection -----------------------------------------------------------
    def inject(self, collection: str, rec_id: str, field: str, value: str) -> None:
        rec = self._find(collection, rec_id)
        if rec is None:
            raise KeyError(f"injection target {collection}/{rec_id} not found")
        rec[field] = value

    # ---- dispatch ------------------------------------------------------------
    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        spec = self.tools.get(name)
        if spec is None:
            result = {"error": f"unknown tool {name}"}
        else:
            try:
                result = getattr(self, f"_kind_{spec['kind']}")(spec, dict(args or {}))
            except Exception as e:  # noqa: BLE001
                result = {"error": f"tool {name} failed: {type(e).__name__}: {e}"}
        result = copy.deepcopy(result)
        self.calls.append({"tool": name, "args": copy.deepcopy(dict(args or {})), "result": result})
        return result

    # ---- kinds ---------------------------------------------------------------
    def _kind_search(self, spec, args) -> dict[str, Any]:
        q = str(args.get("query", "")).lower()
        hits = [r for r in self._collection(spec["collection"]) if q in _searchable_text(r)]
        return {"total": len(hits), "records": hits}

    def _kind_get(self, spec, args) -> dict[str, Any]:
        rec_id = args.get(spec["id_param"])
        rec = self._find(spec["collection"], rec_id)
        if rec is None:
            return {"error": "NOT_FOUND", "message": f"No record {rec_id} in {spec['collection']}"}
        out = dict(rec)
        # convenience: resolve an owner_id to the owner record if present
        if "owner_id" in rec:
            owner = self._find("users", rec["owner_id"])
            if owner:
                out["owner"] = owner
        return out

    def _kind_list(self, spec, args) -> dict[str, Any]:
        recs = list(self._collection(spec["collection"]))
        pf, pp = spec.get("parent_field"), spec.get("parent_param")
        if pf and pp and args.get(pp) is not None:
            recs = [r for r in recs if r.get(pf) == args[pp]]
        mx = args.get("max_results")
        if isinstance(mx, int):
            recs = recs[:mx]
        return {"total": len(recs), "records": recs}

    def _kind_update(self, spec, args) -> dict[str, Any]:
        rec = self._find(spec["collection"], args.get(spec["id_param"]))
        if rec is None:
            return {"error": "NOT_FOUND", "message": f"No record {args.get(spec['id_param'])}"}
        changed = {}
        for f in spec.get("writable", []):
            if f in args and args[f] is not None:
                rec[f] = args[f]
                changed[f] = args[f]
        self.writes.append({"tool": spec["name"], "collection": spec["collection"],
                            "id": rec.get("id"), "changed": changed})
        return {"success": True, "id": rec.get("id"), "updated_fields": list(changed)}

    def _kind_create(self, spec, args) -> dict[str, Any]:
        rec = {"id": f"{spec['collection']}-{uuid.uuid4().hex[:8]}", **args}
        self._collection(spec["collection"]).append(rec)
        self.writes.append({"tool": spec["name"], "collection": spec["collection"],
                            "id": rec["id"], "changed": dict(args)})
        return {"success": True, "id": rec["id"]}

    def _kind_send(self, spec, args) -> dict[str, Any]:
        to = args.get("to") or []
        if isinstance(to, str):
            to = [to]
        cc = args.get("cc") or []
        bcc = args.get("bcc") or []
        if isinstance(cc, str):
            cc = [cc]
        if isinstance(bcc, str):
            bcc = [bcc]
        msg = {"id": f"msg-{uuid.uuid4().hex[:8]}", "channel": "email", "tool": spec["name"],
               "to": to, "cc": cc, "bcc": bcc, "destination": [*to, *cc, *bcc],
               "subject": args.get("subject", ""), "body": args.get("body", "")}
        self.outbox.append(msg)
        return {"success": True, "id": msg["id"], "labelIds": ["SENT"]}

    def _kind_post(self, spec, args) -> dict[str, Any]:
        dest = args.get(spec["channel_param"], "")
        text = args.get(spec["text_param"], "")
        msg = {"id": f"post-{uuid.uuid4().hex[:8]}", "channel": "chat", "tool": spec["name"],
               "destination": [dest], "subject": "", "body": text}
        self.outbox.append(msg)
        return {"success": True, "id": msg["id"]}


def schemas_for(connectors: list[str]) -> list[dict[str, Any]]:
    return [{"name": s["name"], "description": s["description"], "parameters": s["parameters"]}
            for s in tool_specs(connectors)]


def schemas_text(connectors: list[str]) -> str:
    import json
    return json.dumps(schemas_for(connectors), indent=1)
