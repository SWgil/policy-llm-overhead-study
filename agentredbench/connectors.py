"""Connector registry for the AgentRedBench-style harness.

Each connector is a list of tool specs. A tool spec is data, not code: the
generic MockEnv in mock_integrations.py dispatches on `kind` so new connectors
(and new scenarios) are added declaratively, without touching the engine. This
is what makes attack diversification "data-driven" — the paper spans 24
integrations, and here a new one is a registry entry plus a scenario YAML.

Handler kinds (see MockEnv.call):
  search  — args {query}; returns records in `collection` matching the query
  get     — args {<id_param>}; returns one record by id
  list    — args {<parent_param>?}; returns records in `collection`
            (optionally filtered where record[parent_field] == parent value)
  update  — args {<id_param>, <writable fields>}; mutates a record, logs a write
  create  — args {...}; appends a new record to `collection`
  send    — args {to, subject?, body, cc?, bcc?}; appends an email to the outbox
  post    — args {<channel_param>, <text_param>}; appends a chat message to the outbox

Fields on a spec:
  name, description, parameters  — the tool declaration the model sees
  kind                           — one of the above
  collection                     — which seed_state list it reads/writes
  id_param                       — arg name carrying the record id (get/update)
  parent_param / parent_field    — list filtering (list)
  writable                       — fields update may change (update)
  channel_param / text_param     — post
"""

from __future__ import annotations

from typing import Any

_STR = {"type": "string"}
_STRLIST = {"type": "array", "items": {"type": "string"}}


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


# Reusable email sender (Gmail / Outlook share this shape).
def _send_email(name: str, desc: str) -> dict[str, Any]:
    return {"name": name, "kind": "send", "description": desc,
            "parameters": _obj({"to": _STRLIST, "cc": _STRLIST, "bcc": _STRLIST,
                                 "subject": _STR, "body": _STR}, ["to", "subject", "body"])}


CONNECTORS: dict[str, list[dict[str, Any]]] = {
    # ---------------------------------------------------------------- salesforce
    "salesforce": [
        {"name": "salesforce_search_accounts", "kind": "search", "collection": "accounts",
         "description": "Search Salesforce accounts by name or id substring.",
         "parameters": _obj({"query": _STR}, ["query"])},
        {"name": "salesforce_get_account", "kind": "get", "collection": "accounts", "id_param": "account_id",
         "description": "Get a Salesforce account record, including its owner (the internal account executive responsible for it).",
         "parameters": _obj({"account_id": _STR}, ["account_id"])},
        {"name": "salesforce_get_user", "kind": "get", "collection": "users", "id_param": "user_id",
         "description": "Get a Salesforce user record by id.",
         "parameters": _obj({"user_id": _STR}, ["user_id"])},
        {"name": "salesforce_list_notes", "kind": "list", "collection": "notes",
         "parent_param": "account_id", "parent_field": "account_id",
         "description": "List notes attached to an account.",
         "parameters": _obj({"account_id": _STR}, ["account_id"])},
        {"name": "salesforce_get_note", "kind": "get", "collection": "notes", "id_param": "note_id",
         "description": "Get the full content of a note.",
         "parameters": _obj({"note_id": _STR}, ["note_id"])},
        {"name": "salesforce_update_note", "kind": "update", "collection": "notes", "id_param": "note_id",
         "writable": ["body", "title"], "description": "Replace the body (and optionally title) of an existing note.",
         "parameters": _obj({"note_id": _STR, "body": _STR, "title": _STR}, ["note_id", "body"])},
        {"name": "salesforce_create_note", "kind": "create", "collection": "notes",
         "description": "Create a new note on an account.",
         "parameters": _obj({"account_id": _STR, "title": _STR, "body": _STR}, ["account_id", "title", "body"])},
    ],
    # --------------------------------------------------------------------- gmail
    "gmail": [
        _send_email("gmail_send_message", "Send an email from the user's Gmail account (also used to reply)."),
        {"name": "gmail_list_messages", "kind": "list", "collection": "inbox",
         "description": "List messages in the user's inbox (most recent first).",
         "parameters": _obj({"query": _STR, "max_results": {"type": "integer"}}, [])},
        {"name": "gmail_get_message", "kind": "get", "collection": "inbox", "id_param": "message_id",
         "description": "Get the full body and headers of an inbox message.",
         "parameters": _obj({"message_id": _STR}, ["message_id"])},
    ],
    # ------------------------------------------------------------------ calendar
    "calendar": [
        {"name": "calendar_list_events", "kind": "list", "collection": "events",
         "description": "List calendar events in a date range (most recent first).",
         "parameters": _obj({"start": _STR, "end": _STR}, [])},
        {"name": "calendar_get_event", "kind": "get", "collection": "events", "id_param": "event_id",
         "description": "Get a calendar event, including its full description / prep notes.",
         "parameters": _obj({"event_id": _STR}, ["event_id"])},
    ],
    # ---------------------------------------------------------------------- jira
    "jira": [
        {"name": "jira_list_issues", "kind": "list", "collection": "issues",
         "description": "List Jira issues (optionally filtered by project).",
         "parameters": _obj({"project": _STR}, [])},
        {"name": "jira_get_issue", "kind": "get", "collection": "issues", "id_param": "issue_id",
         "description": "Get a Jira issue, including its description.",
         "parameters": _obj({"issue_id": _STR}, ["issue_id"])},
        {"name": "jira_update_issue", "kind": "update", "collection": "issues", "id_param": "issue_id",
         "writable": ["description", "priority", "status", "assignee"],
         "description": "Update fields on a Jira issue.",
         "parameters": _obj({"issue_id": _STR, "description": _STR, "priority": _STR,
                             "status": _STR, "assignee": _STR}, ["issue_id"])},
        {"name": "jira_create_comment", "kind": "post", "collection": "issue_comments",
         "channel_param": "issue_id", "text_param": "body",
         "description": "Post a comment on a Jira issue.",
         "parameters": _obj({"issue_id": _STR, "body": _STR}, ["issue_id", "body"])},
    ],
    # --------------------------------------------------------------------- slack
    "slack": [
        {"name": "slack_list_channels", "kind": "list", "collection": "channels",
         "description": "List Slack channels the user can post to.",
         "parameters": _obj({}, [])},
        {"name": "slack_list_messages", "kind": "list", "collection": "slack_messages",
         "parent_param": "channel", "parent_field": "channel",
         "description": "List recent messages in a Slack channel.",
         "parameters": _obj({"channel": _STR}, ["channel"])},
        {"name": "slack_post_message", "kind": "post", "collection": "slack_outbox",
         "channel_param": "channel", "text_param": "text",
         "description": "Post a message to a Slack channel.",
         "parameters": _obj({"channel": _STR, "text": _STR}, ["channel", "text"])},
    ],
}


def tool_specs(connectors: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in connectors:
        if c not in CONNECTORS:
            raise KeyError(f"unknown connector {c!r}; known: {sorted(CONNECTORS)}")
        out.extend(CONNECTORS[c])
    return out
