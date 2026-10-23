"""Transparent, rule-based parcel delay assessments."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Parcel


ACTIVE_STATUSES = {
    Parcel.Status.REGISTERED,
    Parcel.Status.IN_TRANSIT,
    Parcel.Status.FAILED,
    Parcel.Status.SCHEDULED_FOR_RETRY,
}


def _threshold(setting_name, default_hours):
    """Read a threshold in hours so deployments can tune it without code edits."""
    return timedelta(hours=getattr(settings, setting_name, default_hours))


def assess_parcel_delay_risk(parcel, now=None):
    """Return a risk level and actionable reasons using only recorded facts."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    reasons = []
    level = "NO_CURRENT_RISK"

    def add(reason, action, reason_level):
        nonlocal level
        reasons.append({"message": reason, "action": action})
        priority = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        if priority.get(reason_level, 0) > priority.get(level, 0):
            level = reason_level

    if parcel.status not in ACTIVE_STATUSES:
        return {"level": level, "reasons": reasons}

    if parcel.expected_delivery_date < today:
        add(
            f"Expected delivery date passed on {parcel.expected_delivery_date:%d %b %Y}.",
            "Review the shipment and contact the customer with an updated delivery plan.",
            "HIGH",
        )

    if parcel.status in {
        Parcel.Status.FAILED,
        Parcel.Status.SCHEDULED_FOR_RETRY,
    } and parcel.delivery_attempts:
        failure = parcel.get_failure_reason_display() or "reason not recorded"
        risk_level = "HIGH" if parcel.delivery_attempts >= 2 else "MEDIUM"
        add(
            f"{parcel.delivery_attempts} failed delivery attempt(s); latest recorded reason: {failure}.",
            "Review the retry plan and confirm the delivery details with the customer.",
            risk_level,
        )

    if parcel.assigned_agent_id is None and parcel.unassigned_since:
        age = now - parcel.unassigned_since
        threshold = _threshold("PARCEL_UNASSIGNED_RISK_HOURS", 24)
        if age >= threshold:
            level_for_age = "HIGH" if age >= threshold * 2 else "MEDIUM"
            add(
                f"No delivery agent has been assigned for {int(age.total_seconds() // 3600)} hour(s).",
                "Assign an active delivery agent.",
                level_for_age,
            )

    if parcel.status == Parcel.Status.IN_TRANSIT:
        events = getattr(parcel, "_prefetched_objects_cache", {}).get("history")
        if events is None:
            events = parcel.history.all()
        transit_events = [
            event for event in events
            if (event.new_status or event.status) == Parcel.Status.IN_TRANSIT
        ]
        if transit_events:
            latest_transit = max(transit_events, key=lambda event: event.created_at)
            transit_age = now - latest_transit.created_at
            if transit_age >= _threshold("PARCEL_LONG_TRANSIT_RISK_HOURS", 48):
                add(
                    f"Parcel has remained in transit since {latest_transit.created_at:%d %b %Y %H:%M}.",
                    "Ask the assigned agent to confirm the parcel's location and next step.",
                    "HIGH",
                )

    days_until_due = (parcel.expected_delivery_date - today).days
    if 0 <= days_until_due <= getattr(settings, "PARCEL_UPCOMING_DEADLINE_DAYS", 2):
        if parcel.status in {
            Parcel.Status.REGISTERED,
            Parcel.Status.FAILED,
            Parcel.Status.SCHEDULED_FOR_RETRY,
        }:
            add(
                f"Expected delivery is in {days_until_due} day(s), but the parcel is not currently in transit.",
                "Confirm assignment or retry arrangements before the delivery date.",
                "MEDIUM",
            )
        elif level == "NO_CURRENT_RISK":
            add(
                f"Expected delivery is in {days_until_due} day(s).",
                "Monitor the shipment and follow up if progress stops.",
                "LOW",
            )

    return {"level": level, "reasons": reasons}
