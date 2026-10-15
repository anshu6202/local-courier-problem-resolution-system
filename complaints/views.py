from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden

from parcels.models import Parcel
from .forms import ComplaintForm
from .models import Complaint
from accounts.models import User
from django import forms
from django.db import transaction
from .models import Complaint, ComplaintHistory


@login_required
def complaint_create(request):
    if request.method == "POST":
        form = ComplaintForm(request.POST)

        if form.is_valid():
            tracking_id = form.cleaned_data["tracking_id"].strip()

            parcel = get_object_or_404(
                Parcel,
                tracking_id=tracking_id,
            )

            # Only the customer who registered the parcel
            # or its assigned agent may submit a complaint.
            is_owner = parcel.created_by_id == request.user.id
            is_assigned_agent = (
                parcel.assigned_agent_id == request.user.id
                and getattr(request.user, "role", None) == "AGENT"
            )

            if not (is_owner or is_assigned_agent):
                messages.error(
                    request,
                    "You are not authorized to complain about this parcel.",
                )
                return redirect("complaint_create")

            complaint = form.save(commit=False)
            complaint.parcel = parcel
            complaint.reported_by = request.user
            complaint.save()

            messages.success(
                request,
                "Your complaint has been submitted successfully.",
            )
            return redirect("my_complaints")
    else:
        form = ComplaintForm()

    return render(
        request,
        "complaints/complaint_form.html",
        {"form": form},
    )


@login_required
def my_complaints(request):
    complaints = Complaint.objects.filter(
        reported_by=request.user
    ).select_related("parcel", "assigned_agent").order_by("-created_at")

    return render(
        request,
        "complaints/my_complaints.html",
        {"complaints": complaints},
    )




@login_required
def complaint_admin_list(request):
    if not (
        request.user.is_superuser
        or getattr(request.user, "role", None) == "ADMIN"
    ):
        return HttpResponseForbidden("Admin access only.")

    complaints = Complaint.objects.select_related(
        "parcel", "reported_by", "assigned_agent"
    ).order_by("-created_at")

    agents = User.objects.filter(role="AGENT", is_active=True)

    if request.method == "POST":
        complaint_id = request.POST.get("complaint_id")
        agent_id = request.POST.get("agent_id")
        status = request.POST.get("status")

        complaint = get_object_or_404(
            Complaint,
            pk=complaint_id,
        )

        # 1. Save se pehle purana status capture karein
        old_status = complaint.status

        if agent_id:
            agent = get_object_or_404(
                agents,
                pk=agent_id,
            )
            complaint.assigned_agent = agent

        allowed_statuses = [
            Complaint.Status.OPEN,
            Complaint.Status.IN_PROGRESS,
        ]

        if status in allowed_statuses:
            complaint.status = status

        # 2. Changes ko save karein
        complaint.save()

        # 3. Agar status change hua hai, toh history create karein
        if complaint.status != old_status:
            ComplaintHistory.objects.create(
                complaint=complaint,
                changed_by=request.user,
                old_status=old_status,
                new_status=complaint.status,
                note="Status updated by admin.",
            )

        return redirect("complaint_admin_list")

    return render(
        request,
        "complaints/admin_complaints.html",
        {
            "complaints": complaints,
            "agents": agents,
            "statuses": [
                (Complaint.Status.OPEN, Complaint.Status.OPEN.label),
                (Complaint.Status.IN_PROGRESS, Complaint.Status.IN_PROGRESS.label),
            ],
        },
    )






class ComplaintResolutionForm(forms.Form):
    resolution_details = forms.CharField(
        label="Resolution Details",
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "Explain how the complaint was resolved...",
        }),
    )


@login_required
def agent_complaints(request):
    if getattr(request.user, "role", None) != "AGENT":
        return HttpResponseForbidden("Agents only.")

    complaints = Complaint.objects.filter(
        assigned_agent=request.user
    ).select_related("parcel", "reported_by").order_by("-created_at")

    return render(
        request,
        "complaints/agent_complaints.html",
        {"complaints": complaints},
    )


@login_required
def resolve_complaint(request, complaint_id):
    if getattr(request.user, "role", None) != "AGENT":
        return HttpResponseForbidden("Agents only.")

    complaint = get_object_or_404(
        Complaint,
        pk=complaint_id,
        assigned_agent=request.user,
    )

    if complaint.status == Complaint.Status.RESOLVED:
        messages.info(request, "This complaint is already resolved.")
        return redirect("agent_complaints")

    if request.method == "POST":
        form = ComplaintResolutionForm(request.POST)

        if form.is_valid():
            details = form.cleaned_data["resolution_details"].strip()

            if not details:
                form.add_error(
                    "resolution_details",
                    "Please enter resolution details.",
                )
            else:
                with transaction.atomic():
                    # 1. Status change karne se pehle purana status capture karein
                    old_status = complaint.status

                    # 2. Complaint details aur status update karke save karein
                    complaint.resolution_details = details
                    complaint.status = Complaint.Status.RESOLVED
                    complaint.save(
                        update_fields=[
                            "resolution_details",
                            "status",
                            "updated_at",
                        ]
                    )

                    # 3. Save hone ke baad history record create karein
                    ComplaintHistory.objects.create(
                        complaint=complaint,
                        changed_by=request.user,
                        old_status=old_status,
                        new_status=Complaint.Status.RESOLVED,
                        note=details,
                    )

                messages.success(
                    request,
                    "Complaint resolved successfully.",
                )
                return redirect("agent_complaints")
    else:
        form = ComplaintResolutionForm()

    return render(
        request,
        "complaints/resolve_complaint.html",
        {"complaint": complaint, "form": form},
    )
