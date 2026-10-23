import csv
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.shortcuts import render
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone

from parcels.models import Parcel
from parcels.delay_risk import ACTIVE_STATUSES, assess_parcel_delay_risk
from complaints.models import Complaint, ComplaintNotification
from .permissions import role_required
from .forms import CustomerRegistrationForm

class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy("dashboard")


def customer_register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Your customer account is ready. Please sign in.")
            return redirect("login")
    else:
        form = CustomerRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})




@login_required
def dashboard(request):
    user = request.user

    context = {"user": user}

    if user.is_superuser or getattr(user, "role", None) == "ADMIN":
        context["dashboard_type"] = "admin"

        context["total_parcels"] = Parcel.objects.count()
        context["delivered_parcels"] = Parcel.objects.filter(
            status=Parcel.Status.DELIVERED
        ).count()
        context["in_transit_parcels"] = Parcel.objects.filter(
            status=Parcel.Status.IN_TRANSIT
        ).count()
        context["unassigned_parcels"] = Parcel.objects.filter(
            assigned_agent__isnull=True
        ).exclude(status=Parcel.Status.DELIVERED).count()
        context["failed_parcels"] = Parcel.objects.filter(
            status__in=[
                Parcel.Status.FAILED,
                Parcel.Status.SCHEDULED_FOR_RETRY,
                Parcel.Status.RTO_INITIATED,
            ]
        ).count()

        context["open_complaints"] = Complaint.objects.filter(
            status=Complaint.Status.OPEN
        ).count()
        context["active_complaints"] = Complaint.objects.filter(
            status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS]
        ).count()
        context["in_progress_complaints"] = Complaint.objects.filter(
            status=Complaint.Status.IN_PROGRESS
        ).count()
        context["resolved_complaints"] = Complaint.objects.filter(
            status=Complaint.Status.RESOLVED
        ).count()

        context["delivery_chart_labels"] = [
            "Registered",
            "In Transit",
            "Delivered",
            "Failed",
        ]

        context["delivery_chart_data"] = [
            Parcel.objects.filter(status=Parcel.Status.REGISTERED).count(),
            context["in_transit_parcels"],
            context["delivered_parcels"],
            context["failed_parcels"],
        ]

        context["complaint_chart_labels"] = [
            "Open",
            "In Progress",
            "Resolved",
        ]

        context["complaint_chart_data"] = [
            context["open_complaints"],
            context["in_progress_complaints"],
            context["resolved_complaints"],
        ]

        today = timezone.localdate()

        context["overdue_parcels"] = Parcel.objects.filter(
            expected_delivery_date__lt=today
        ).exclude(
            status=Parcel.Status.DELIVERED
        ).order_by("expected_delivery_date")

        context["overdue_count"] = context["overdue_parcels"].count()

        context["unresolved_complaints"] = Complaint.objects.filter(
            status__in=[
                Complaint.Status.OPEN,
                Complaint.Status.IN_PROGRESS,
            ]
        ).select_related(
            "parcel",
            "assigned_agent",
        ).order_by("created_at")

        context["unresolved_count"] = context["unresolved_complaints"].count()
        context["escalated_complaints"] = Complaint.objects.filter(
            is_escalated=True,
            status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
        ).select_related("parcel", "assigned_agent").order_by("sla_deadline")
        sla_now = timezone.now()
        active_statuses = [Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS]
        context["overdue_complaints"] = Complaint.objects.filter(
            status__in=active_statuses, sla_deadline__lte=sla_now
        ).select_related("parcel").order_by("sla_deadline")
        context["overdue_complaint_count"] = context["overdue_complaints"].count()
        approaching_hours = max(0, int(getattr(settings, "COMPLAINT_SLA_APPROACHING_HOURS", 4)))
        context["approaching_complaints"] = Complaint.objects.filter(
            status__in=active_statuses,
            is_escalated=False,
            sla_deadline__gt=sla_now,
            sla_deadline__lte=sla_now + timedelta(hours=approaching_hours),
        ).select_related("parcel").order_by("sla_deadline")
        context["approaching_complaint_count"] = context["approaching_complaints"].count()
        context["escalated_complaint_count"] = context["escalated_complaints"].count()
        context["unread_complaint_notifications"] = ComplaintNotification.objects.filter(
            recipient=user, is_read=False
        ).count()

        risk_cases = []
        active_parcels = Parcel.objects.filter(
            status__in=ACTIVE_STATUSES
        ).select_related("assigned_agent").prefetch_related("history").order_by(
            "expected_delivery_date", "created_at"
        )
        for parcel in active_parcels:
            assessment = assess_parcel_delay_risk(parcel)
            if assessment["level"] != "NO_CURRENT_RISK":
                risk_cases.append({"parcel": parcel, **assessment})
        context["delay_risk_cases"] = risk_cases
        context["delay_risk_high_count"] = sum(
            case["level"] == "HIGH" for case in risk_cases
        )
        context["delay_risk_medium_count"] = sum(
            case["level"] == "MEDIUM" for case in risk_cases
        )
        context["delay_risk_low_count"] = sum(
            case["level"] == "LOW" for case in risk_cases
        )
        

    elif getattr(user, "role", None) == "AGENT":
        context["dashboard_type"] = "agent"

        context["assigned_parcels"] = Parcel.objects.filter(
            assigned_agent=user
        ).count()
        context["pending_deliveries"] = Parcel.objects.filter(
            assigned_agent=user,
            status__in=[
                Parcel.Status.REGISTERED,
                Parcel.Status.IN_TRANSIT,
                Parcel.Status.SCHEDULED_FOR_RETRY,
            ],
        ).count()
        context["assigned_complaints"] = Complaint.objects.filter(
            assigned_agent=user
        ).count()
        context["pending_complaints"] = Complaint.objects.filter(
            assigned_agent=user,
            status__in=[
                Complaint.Status.OPEN,
                Complaint.Status.IN_PROGRESS,
            ],
        ).count()
        context["sla_complaints"] = Complaint.objects.filter(
            assigned_agent=user,
            status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
        ).select_related("parcel").order_by("sla_deadline")[:8]

    else:
        context["dashboard_type"] = "customer"

        context["my_parcels"] = Parcel.objects.filter(
            customer=user
        ).count()
        context["my_complaints"] = Complaint.objects.filter(
            customer=user
        ).count()

    return render(
        request,
        "accounts/dashboard.html",
        context,
    )


@role_required("ADMIN")
def admin_dashboard(request):
    return dashboard(request)


@login_required
def export_parcel_report(request):
    if not (
        request.user.is_superuser
        or getattr(request.user, "role", None) == "ADMIN"
    ):
        return HttpResponse("Admin access only.", status=403)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="parcel_report.csv"'
    )

    writer = csv.writer(response)

    writer.writerow([
        "Tracking ID",
        "Sender",
        "Receiver",
        "Delivery Address",
        "Expected Delivery Date",
        "Status",
        "Assigned Agent",
        "Created At",
    ])

    parcels = Parcel.objects.select_related(
        "assigned_agent"
    ).order_by("-created_at")

    for parcel in parcels:
        writer.writerow([
            parcel.tracking_id,
            parcel.sender_name,
            parcel.receiver_name,
            parcel.delivery_address,
            parcel.expected_delivery_date,
            parcel.get_status_display(),
            (
                parcel.assigned_agent.username
                if parcel.assigned_agent else "Not assigned"
            ),
            parcel.created_at.strftime("%Y-%m-%d %H:%M"),
        ])

    return response
