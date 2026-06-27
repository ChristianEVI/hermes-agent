"""The request approval workflow — a small, explicit state machine.

States
------
* ``pending``    — submitted, awaiting a decision (Beantragt)
* ``approved``   — granted (Genehmigt)
* ``rejected``   — declined (Abgelehnt / Not Approved)
* ``cancelled``  — withdrawn by the employee (Zurückgezogen)

The :data:`TRANSITIONS` table is the single source of truth; the web layer uses
:data:`GRAPH` to draw the flow diagram with the current state highlighted.
"""

from __future__ import annotations

# Allowed transitions: state -> {action: next_state}
TRANSITIONS: dict[str, dict[str, str]] = {
    "pending": {
        "approve": "approved",
        "reject": "rejected",
        "cancel": "cancelled",
    },
    "approved": {
        # An approval can be revoked (e.g. plans change) back to rejected.
        "revoke": "rejected",
        "cancel": "cancelled",
    },
    "rejected": {},
    "cancelled": {},
}

# Which role may perform which action.
#   employee  — may cancel their own request
#   decider   — manager of the employee, or an admin/Chef
ACTION_ROLES: dict[str, set[str]] = {
    "approve": {"decider"},
    "reject": {"decider"},
    "revoke": {"decider"},
    "cancel": {"employee", "decider"},
}

TERMINAL = {"approved", "rejected", "cancelled"}

# Human-readable labels (German) for the UI.
LABELS = {
    "pending": "Beantragt (Pending)",
    "approved": "Genehmigt (Approved)",
    "rejected": "Abgelehnt (Not Approved)",
    "cancelled": "Zurückgezogen (Cancelled)",
}

# Static description of the graph for rendering (nodes + directed edges).
GRAPH = {
    "nodes": [
        {"id": "pending", "label": LABELS["pending"]},
        {"id": "approved", "label": LABELS["approved"]},
        {"id": "rejected", "label": LABELS["rejected"]},
        {"id": "cancelled", "label": LABELS["cancelled"]},
    ],
    "edges": [
        {"from": "pending", "to": "approved", "action": "approve"},
        {"from": "pending", "to": "rejected", "action": "reject"},
        {"from": "pending", "to": "cancelled", "action": "cancel"},
        {"from": "approved", "to": "rejected", "action": "revoke"},
    ],
}


class WorkflowError(ValueError):
    """Raised on an illegal transition."""


def can(action: str, from_state: str) -> bool:
    return action in TRANSITIONS.get(from_state, {})


def next_state(action: str, from_state: str) -> str:
    if not can(action, from_state):
        raise WorkflowError(
            f"Aktion '{action}' ist im Status '{from_state}' nicht erlaubt."
        )
    return TRANSITIONS[from_state][action]


def role_may(action: str, role: str) -> bool:
    return role in ACTION_ROLES.get(action, set())
