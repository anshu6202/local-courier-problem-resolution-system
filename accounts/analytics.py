"""Admin-only operational analytics, derived from recorded LCPS events."""

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import (
    Avg,
    Count,
    DurationField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
)
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render
from django.utils import timezone

from complaints.models import Complaint
from parcels.delay_risk import ACTIVE_STATUSES, assess_parcel_delay_risk
from parcels.models import Parcel, ParcelHistory
from .permissions import role_required


def _selected_period(request):
    today = timezone.localdate()
    period = request.GET.get("period", "30")
    errors = []

    if period == "7":
        start, end = today - timedelta(days=6), today
    elif period == "custom":
        try:
            start = date_from_input(request.GET.get("start_date", ""))
            end = date_from_input(request.GET.get("end_date", ""))
            if end < start:
                raise ValueError("End date must be on or after the start date.")
        except ValueError as exc:
            errors.append(str(exc))
            period = "30"
            start, end = today - timedelta(days=29), today
    else:
        if period not in {"30", ""}:
            errors.append("Choose a valid date range.")
        period = "30"
        start, end = today - timedelta(days=29), today

    return period, start, end, errors


def date_from_input(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _range_datetimes(start, end):
    start_dt = timezone.make_aware(datetime.combine(start, time.min))
    end_dt = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
    return start_dt, end_dt


def _bucket_labels(start, end, monthly):
    buckets = []
    if monthly:
        cursor = start.replace(day=1)
        last = end.replace(day=1)
        while cursor <= last:
            buckets.append(cursor)
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        return buckets
    cursor = start
    while cursor <= end:
        buckets.append(cursor)
        cursor += timedelta(days=1)
    return buckets


def _chart_series(grouped_rows, buckets, monthly):
    values_by_bucket = {}
    for row in grouped_rows:
        value = row["bucket"]
        key = value.date() if isinstance(value, datetime) else value
        if monthly:
            key = key.replace(day=1)
        values_by_bucket[key] = row["total"]
    return [values_by_bucket.get(bucket, 0) for bucket in buckets]


@role_required("ADMIN")
def courier_analytics(request):
    period, start, end, filter_errors = _selected_period(request)
    start_dt, end_dt = _range_datetimes(start, end)
    parcel_window = Parcel.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt)
    complaint_window = Complaint.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt)
    event_window = ParcelHistory.objects.filter(created_at__gte=start_dt, created_at__lt=end_dt)

    status_rows = parcel_window.values("status").annotate(total=Count("id"))
    status_counts = {row["status"]: row["total"] for row in status_rows}
    status_choices = list(Parcel.Status.choices)
    status_labels = [label for _, label in status_choices]
    status_values = [status_counts.get(value, 0) for value, _ in status_choices]

    delivered_events = event_window.filter(new_status=Parcel.Status.DELIVERED)
    delivered_count = delivered_events.count()
    on_time_count = delivered_events.annotate(
        delivery_date=TruncDate("created_at"),
    ).filter(parcel__expected_delivery_date__gte=F("delivery_date")).count()
    late_count = delivered_count - on_time_count

    failure_events = event_window.filter(
        new_status__in=[Parcel.Status.SCHEDULED_FOR_RETRY, Parcel.Status.RTO_INITIATED],
        note__startswith="Delivery attempt ",
    ).count()
    outcome_count = delivered_count + failure_events
    failure_rate = (failure_events / outcome_count * 100) if outcome_count else None

    monthly = (end - start).days > 62
    truncation = TruncMonth if monthly else TruncDate
    buckets = _bucket_labels(start, end, monthly)
    booking_rows = list(
        parcel_window.annotate(bucket=truncation("created_at"))
        .values("bucket").annotate(total=Count("id")).order_by("bucket")
    )
    delivery_rows = list(
        delivered_events.annotate(bucket=truncation("created_at"))
        .values("bucket").annotate(total=Count("id")).order_by("bucket")
    )
    trend_labels = [bucket.strftime("%b %Y" if monthly else "%d %b") for bucket in buckets]
    booking_trend = _chart_series(booking_rows, buckets, monthly)
    delivery_trend = _chart_series(delivery_rows, buckets, monthly)

    category_rows = complaint_window.values("category").annotate(total=Count("id"))
    category_counts = {row["category"]: row["total"] for row in category_rows}
    complaint_labels = [label for _, label in Complaint.Category.choices]
    complaint_values = [
        category_counts.get(value, 0) for value, _ in Complaint.Category.choices
    ]
    complaint_status_counts = complaint_window.aggregate(
        open_count=Count("id", filter=Q(status=Complaint.Status.OPEN)),
        in_progress_count=Count("id", filter=Q(status=Complaint.Status.IN_PROGRESS)),
        resolved_count=Count("id", filter=Q(status=Complaint.Status.RESOLVED)),
        escalated_count=Count("id", filter=Q(is_escalated=True)),
    )
    overdue_complaint_count = Complaint.objects.filter(
        status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
        sla_deadline__lte=timezone.now(),
    ).count()

    resolved_complaints = complaint_window.filter(
        status=Complaint.Status.RESOLVED,
        resolved_at__isnull=False,
        resolved_at__gte=start_dt,
        resolved_at__lt=end_dt,
    ).annotate(
        resolution_duration=ExpressionWrapper(
            F("resolved_at") - F("created_at"), output_field=DurationField()
        )
    )
    average_resolution = resolved_complaints.aggregate(
        average=Avg("resolution_duration")
    )["average"]
    average_resolution_hours = (
        round(average_resolution.total_seconds() / 3600, 1)
        if average_resolution is not None else None
    )

    agent_rows = list(
        event_window.filter(changed_by__role="AGENT")
        .values("changed_by_id", "changed_by__username")
        .annotate(
            delivered=Count("id", filter=Q(new_status=Parcel.Status.DELIVERED)),
            failed_attempts=Count(
                "id",
                filter=Q(
                    new_status__in=[Parcel.Status.SCHEDULED_FOR_RETRY, Parcel.Status.RTO_INITIATED],
                    note__startswith="Delivery attempt ",
                ),
            ),
        )
    )
    event_metrics = {row["changed_by_id"]: row for row in agent_rows}
    Agent = get_user_model()
    agents = Agent.objects.filter(role="AGENT").annotate(
        assigned_count=Count(
            "assigned_parcels",
            filter=Q(
                assigned_parcels__created_at__gte=start_dt,
                assigned_parcels__created_at__lt=end_dt,
            ),
        )
    ).order_by("username")
    agent_performance = []
    for agent in agents:
        outcomes = event_metrics.get(agent.pk, {})
        delivered = outcomes.get("delivered", 0)
        failed_attempts = outcomes.get("failed_attempts", 0)
        completed_outcomes = delivered + failed_attempts
        agent_performance.append({
            "username": agent.username,
            "assigned_count": agent.assigned_count,
            "delivered": delivered,
            "failed_attempts": failed_attempts,
            "success_rate": (
                round(delivered / completed_outcomes * 100, 1)
                if completed_outcomes else None
            ),
        })
    agent_labels = [row["username"] for row in agent_performance]
    agent_delivered = [row["delivered"] for row in agent_performance]
    agent_failed_attempts = [row["failed_attempts"] for row in agent_performance]

    # Alerts are a live operational snapshot; the selected date window is for
    # historical metrics and does not hide current work needing attention.
    today = timezone.localdate()
    overdue_parcels = Parcel.objects.filter(
        expected_delivery_date__lt=today,
        status__in=ACTIVE_STATUSES,
    )
    unassigned_parcels = Parcel.objects.filter(
        status__in=ACTIVE_STATUSES, assigned_agent__isnull=True
    ).count()
    risk_cases = []
    for parcel in Parcel.objects.filter(status__in=ACTIVE_STATUSES).select_related(
        "assigned_agent"
    ).prefetch_related("history"):
        assessment = assess_parcel_delay_risk(parcel)
        if assessment["level"] == "HIGH":
            risk_cases.append({"parcel": parcel, **assessment})

    context = {
        "period": period,
        "start_date": start,
        "end_date": end,
        "filter_errors": filter_errors,
        "parcel_status_counts": status_counts,
        "parcel_status_labels": status_labels,
        "parcel_status_values": status_values,
        "parcel_status_total": sum(status_values),
        "on_time_count": on_time_count,
        "late_count": late_count,
        "delivered_count": delivered_count,
        "failure_events": failure_events,
        "failure_rate": round(failure_rate, 1) if failure_rate is not None else None,
        "trend_labels": trend_labels,
        "booking_trend": booking_trend,
        "delivery_trend": delivery_trend,
        "trend_total": sum(booking_trend) + sum(delivery_trend),
        "complaint_labels": complaint_labels,
        "complaint_values": complaint_values,
        "complaint_total": sum(complaint_values),
        "complaint_status_counts": complaint_status_counts,
        "average_resolution_hours": average_resolution_hours,
        "overdue_complaint_count": overdue_complaint_count,
        "agent_performance": agent_performance,
        "agent_labels": agent_labels,
        "agent_delivered": agent_delivered,
        "agent_failed_attempts": agent_failed_attempts,
        "overdue_parcel_count": overdue_parcels.count(),
        "unassigned_parcel_count": unassigned_parcels,
        "high_risk_parcels": risk_cases,
        "high_risk_parcel_count": len(risk_cases),
        "csv_url": "admin_parcel_export",
    }
    return render(request, "accounts/analytics.html", context)
