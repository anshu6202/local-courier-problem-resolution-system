from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import User
from accounts.permissions import role_required
from parcels.models import Parcel

from .forms import ComplaintForm
from .models import (
    Complaint, ComplaintFeedback, ComplaintHistory, ComplaintNotification,
    ComplaintUpdate,
)


class ComplaintResolutionForm(forms.Form):
    resolution_details = forms.CharField(
        label="Resolution Details",
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Explain how the complaint was resolved...",
            }
        ),
    )


@role_required("CUSTOMER")
def complaint_create(request):
    if request.method == "POST":
        form = ComplaintForm(request.POST)
        if form.is_valid():
            parcel = get_object_or_404(
                Parcel,
                tracking_id=form.cleaned_data["tracking_id"].strip(),
                customer=request.user,
            )
            if parcel.complaints.filter(
                status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS]
            ).exists():
                form.add_error(
                    "tracking_id",
                    "There is already an open complaint for this parcel.",
                )
            else:
                try:
                    with transaction.atomic():
                        complaint = form.save(commit=False)
                        complaint.parcel = parcel
                        complaint.customer = request.user
                        complaint.reported_by = request.user
                        complaint.save()
                        ComplaintHistory.objects.create(
                            complaint=complaint,
                            changed_by=request.user,
                            old_status="",
                            new_status=complaint.status,
                            note="Complaint submitted",
                        )
                except IntegrityError:
                    form.add_error(
                        "tracking_id",
                        "There is already an open complaint for this parcel.",
                    )
                else:
                    messages.success(request, "Your complaint has been submitted.")
                    return redirect("customer_complaints")
    else:
        form = ComplaintForm(
            initial={"tracking_id": request.GET.get("tracking_id", "").strip()}
        )
    return render(request, "complaints/complaint_form.html", {"form": form})


@role_required("CUSTOMER")
def my_complaints(request):
    complaints = Complaint.objects.filter(customer=request.user).select_related(
        "parcel", "assigned_agent"
    ).prefetch_related(
        "feedback",
        Prefetch(
            "updates",
            queryset=ComplaintUpdate.objects.filter(is_internal=False).order_by("created_at"),
            to_attr="customer_visible_updates",
        ),
    ).order_by("-created_at")

    if request.method == "POST":
        complaint = get_object_or_404(
            complaints,
            pk=request.POST.get("complaint_id"),
            status=Complaint.Status.RESOLVED,
        )
        try:
            rating = int(request.POST.get("rating", ""))
        except (TypeError, ValueError):
            rating = 0
        if rating not in range(1, 6):
            messages.error(request, "Choose a rating from 1 to 5.")
        elif hasattr(complaint, "feedback"):
            messages.info(request, "Feedback has already been submitted for this case.")
        else:
            ComplaintFeedback.objects.create(
                complaint=complaint,
                rating=rating,
                comment=request.POST.get("feedback", "").strip()[:2000],
            )
            messages.success(request, "Thanks for sharing feedback on your case.")
        return redirect("customer_complaints")

    return render(request, "complaints/my_complaints.html", {
        "complaints": complaints,
        "now": timezone.now(),
    })


@role_required("ADMIN")
def admin_complaint_notifications(request):
    notifications = ComplaintNotification.objects.filter(
        recipient=request.user
    ).select_related("complaint__parcel")
    return render(request, "complaints/admin_notifications.html", {
        "notifications": notifications,
    })


@role_required("ADMIN")
def mark_complaint_notification_read(request, notification_id):
    if request.method != "POST":
        return redirect("admin_complaint_notifications")
    ComplaintNotification.objects.filter(
        pk=notification_id, recipient=request.user, is_read=False
    ).update(is_read=True)
    return redirect("admin_complaint_notifications")


@role_required("CUSTOMER", "AGENT", "ADMIN")
def complaint_detail(request, complaint_id):
    complaint = get_object_or_404(
        Complaint.objects.select_related("parcel", "customer", "assigned_agent")
        .prefetch_related("updates__author", "history__changed_by"),
        pk=complaint_id,
    )
    is_admin = request.user.is_superuser or request.user.role == User.Role.ADMIN
    is_customer = complaint.customer_id == request.user.id
    is_assigned_agent = complaint.assigned_agent_id == request.user.id
    if not (is_admin or is_customer or is_assigned_agent):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("You are not allowed to view this case.")

    updates = complaint.updates.all()
    if not (is_admin or is_assigned_agent):
        updates = updates.filter(is_internal=False)

    if request.method == "POST":
        message = request.POST.get("message", "").strip()
        if not message:
            messages.error(request, "Enter a message before sending.")
        elif complaint.status == Complaint.Status.RESOLVED:
            messages.error(request, "This case is resolved and no longer accepts replies.")
        else:
            is_internal = bool(request.POST.get("is_internal")) and (is_admin or is_assigned_agent)
            ComplaintUpdate.objects.create(
                complaint=complaint,
                author=request.user,
                message=message[:4000],
                attachment=request.FILES.get("attachment"),
                is_internal=is_internal,
            )
            messages.success(request, "Your update has been added to the case.")
            detail_route = "customer_complaint_detail" if is_customer else "agent_complaint_detail" if is_assigned_agent else "complaint_detail"
            return redirect(detail_route, complaint_id=complaint.id)

    return render(
        request,
        "complaints/complaint_detail.html",
        {"complaint": complaint, "updates": updates, "is_admin": is_admin, "is_assigned_agent": is_assigned_agent},
    )


@role_required("ADMIN")
def complaint_admin_list(request):
    agents = User.objects.filter(
        role=User.Role.AGENT,
        is_active=True,
        is_active_agent=True,
    )
    if request.method == "POST":
        complaint = get_object_or_404(Complaint, pk=request.POST.get("complaint_id"))
        agent_id = request.POST.get("agent_id", "")
        status = request.POST.get("status", "")
        with transaction.atomic():
            if agent_id:
                complaint.assigned_agent = get_object_or_404(agents, pk=agent_id)
            complaint.save(update_fields=["assigned_agent"])
            if status in {Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS} and status != complaint.status:
                try:
                    complaint.transition_to(
                        status,
                        changed_by=request.user,
                        note="Status updated by admin.",
                    )
                except ValidationError as error:
                    messages.error(request, error.messages[0])
        return redirect("admin_complaints")

    complaints = Complaint.objects.select_related(
        "parcel", "customer", "reported_by", "assigned_agent"
    ).order_by("-created_at")
    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "")
    if query:
        complaints = complaints.filter(
            Q(parcel__tracking_id__icontains=query)
            | Q(description__icontains=query)
            | Q(customer__username__icontains=query)
        )
    if selected_status in Complaint.Status.values:
        complaints = complaints.filter(status=selected_status)
    page = Paginator(complaints, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "complaints/admin_complaints.html",
        {
            "complaints": page,
            "agents": agents,
            "page_obj": page,
            "query": query,
            "selected_status": selected_status,
            "all_statuses": Complaint.Status.choices,
            "statuses": [
                (Complaint.Status.OPEN, Complaint.Status.OPEN.label),
                (Complaint.Status.IN_PROGRESS, Complaint.Status.IN_PROGRESS.label),
            ],
        },
    )


@role_required("AGENT")
def agent_complaints(request):
    complaints = Complaint.objects.filter(assigned_agent=request.user).select_related(
        "parcel", "customer"
    ).order_by("-created_at")
    return render(request, "complaints/agent_complaints.html", {"complaints": complaints})


@role_required("AGENT")
def resolve_complaint(request, complaint_id):
    complaint = get_object_or_404(
        Complaint,
        pk=complaint_id,
        assigned_agent=request.user,
    )
    if complaint.status == Complaint.Status.RESOLVED:
        messages.info(request, "This complaint is already resolved.")
        return redirect("agent_assigned_complaints")

    if request.method == "POST":
        form = ComplaintResolutionForm(request.POST)
        if form.is_valid():
            details = form.cleaned_data["resolution_details"].strip()
            if not details:
                form.add_error("resolution_details", "Please enter resolution details.")
            else:
                try:
                    with transaction.atomic():
                        complaint.transition_to(
                            Complaint.Status.RESOLVED,
                            changed_by=request.user,
                            note=details,
                        )
                        complaint.resolution_details = details
                        complaint.save(update_fields=["resolution_details", "updated_at"])
                except ValidationError as error:
                    form.add_error(None, error)
                else:
                    messages.success(request, "Complaint resolved successfully.")
                    return redirect("agent_assigned_complaints")
    else:
        form = ComplaintResolutionForm()

    return render(
        request,
        "complaints/resolve_complaint.html",
        {"complaint": complaint, "form": form},
    )
