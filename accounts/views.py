import csv

from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils import timezone

from parcels.models import Parcel
from complaints.models import Complaint

class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy("dashboard")




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
        context["failed_parcels"] = Parcel.objects.filter(
            status=Parcel.Status.FAILED
        ).count()

        context["open_complaints"] = Complaint.objects.filter(
            status=Complaint.Status.OPEN
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

        # --- AAPKA NAYA CODE ADMIN BLOCK KE ANDAR ---
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

    else:
        context["dashboard_type"] = "customer"

        context["my_parcels"] = Parcel.objects.filter(
            created_by=user
        ).count()
        context["my_complaints"] = Complaint.objects.filter(
            reported_by=user
        ).count()

    return render(
        request,
        "accounts/dashboard.html",
        context,
    )


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
