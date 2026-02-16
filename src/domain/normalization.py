from __future__ import annotations

from typing import Literal


NormalizedCampaignStatus = Literal["DRAFTED", "ACTIVE", "PAUSED", "STOPPED", "COMPLETED"]
NormalizedLeadStatus = Literal[
    "active",
    "paused",
    "unsubscribed",
    "replied",
    "bounced",
    "pending",
    "contacted",
    "connected",
    "not_interested",
    "unknown",
]
NormalizedMessageDirection = Literal["inbound", "outbound", "unknown"]


def normalize_campaign_status(value: str | None) -> NormalizedCampaignStatus:
    if not value:
        return "DRAFTED"
    key = str(value).strip().upper()
    mapping = {
        "DRAFTED": "DRAFTED",
        "DRAFT": "DRAFTED",
        "LAUNCHING": "DRAFTED",
        "QUEUED": "DRAFTED",
        "ACTIVE": "ACTIVE",
        "START": "ACTIVE",
        "STARTED": "ACTIVE",
        "RUNNING": "ACTIVE",
        "PAUSED": "PAUSED",
        "PAUSE": "PAUSED",
        "STOPPED": "STOPPED",
        "STOP": "STOPPED",
        "ARCHIVED": "STOPPED",
        "DELETED": "STOPPED",
        "FAILED": "STOPPED",
        "PENDING DELETION": "STOPPED",
        "COMPLETED": "COMPLETED",
        "DONE": "COMPLETED",
    }
    return mapping.get(key, "DRAFTED")


def normalize_lead_status(value: str | None) -> NormalizedLeadStatus:
    if not value:
        return "unknown"
    key = str(value).strip().lower()
    mapping = {
        "active": "active",
        "verified": "active",
        "paused": "paused",
        "pause": "paused",
        "unsubscribed": "unsubscribed",
        "unsubscribe": "unsubscribed",
        "replied": "replied",
        "reply": "replied",
        "bounced": "bounced",
        "bounce": "bounced",
        "pending": "pending",
        "verifying": "pending",
        "unverified": "pending",
        "unknown": "pending",
        "risky": "pending",
        "inactive": "pending",
        "in_sequence": "active",
        "sequence_finished": "contacted",
        "sequence_stopped": "paused",
        "never_contacted": "pending",
        "contacted": "contacted",
        "connected": "connected",
        "not_interested": "not_interested",
        "not interested": "not_interested",
    }
    return mapping.get(key, "unknown")


def normalize_message_direction(value: str | None) -> NormalizedMessageDirection:
    if not value:
        return "unknown"
    key = str(value).strip().lower()
    if key in {"inbound", "reply", "replied"}:
        return "inbound"
    if key in {"outbound", "sent"}:
        return "outbound"
    return "unknown"
