# Create your views here.
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ParcelForm
from .models import Parcel
from .forms import ParcelStatusUpdateForm


def is_courier_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.role == "ADMIN"
    )


@login_required
def parcel_create(request):
    if not is_courier_admin(request.user):
        return HttpResponseForbidden(
            "Only admins can register parcels."
        )

    if request.method == "POST":
        form = ParcelForm(request.POST)

        if form.is_valid():
            parcel = form.save(commit=False)
            parcel.created_by = request.user
            parcel.save()

            return render(
                request,
                "parcels/parcel_created.html",
                {"parcel": parcel},
            )
    else:
        form = ParcelForm()

    return render(
        request,
        "parcels/parcel_form.html",
        {"form": form},
    )


@login_required
def parcel_list(request):
    if not is_courier_admin(request.user):
        return HttpResponseForbidden(
            "Only admins can view all parcels."
        )

    parcels = Parcel.objects.order_by("-created_at")

    return render(
        request,
        "parcels/parcel_list.html",
        {"parcels": parcels},
    )



def parcel_track(request):
    tracking_id = request.GET.get("tracking_id", "").strip()
    parcel = None
    searched = bool(tracking_id)

    if searched:
        parcel = Parcel.objects.filter(
            tracking_id__iexact=tracking_id
        ).first()

    return render(
        request,
        "parcels/parcel_track.html",
        {
            "parcel": parcel,
            "searched": searched,
            "tracking_id": tracking_id,
        },
    )


@login_required
def agent_parcels(request):
    if request.user.role != "AGENT":
        return HttpResponseForbidden(
            "You are not authorized to view this page."
        )

    parcels = Parcel.objects.filter(
        assigned_agent=request.user
    ).order_by("-created_at")

    return render(
        request,
        "parcels/agent_parcels.html",
        {"parcels": parcels},
    )

@login_required
def update_parcel_status(request, tracking_id):
    if getattr(request.user, "role", None) != "AGENT":
        return HttpResponseForbidden("You are not authorized to access this page.")

    parcel = get_object_or_404(
        Parcel,
        tracking_id=tracking_id,
        assigned_agent=request.user,
    )

    if parcel.status not in ["REGISTERED", "IN_TRANSIT"]:
        messages.error(request, "This parcel can no longer be updated.")
        return redirect("agent_parcels")

    if request.method == "POST":
        form = ParcelStatusUpdateForm(
            request.POST,
            current_status=parcel.status,
        )

        if form.is_valid():
            new_status = form.cleaned_data["status"]

            allowed_transitions = {
                "REGISTERED": ["IN_TRANSIT"],
                "IN_TRANSIT": ["DELIVERED", "FAILED"],
            }

            if new_status not in allowed_transitions.get(
                parcel.status, []
            ):
                return HttpResponseForbidden("Invalid status change.")

            parcel.status = new_status
            parcel.save(update_fields=["status"])

            messages.success(
                request,
                f"Parcel {parcel.tracking_id} status updated successfully.",
            )
            return redirect("agent_parcels")
    else:
        form = ParcelStatusUpdateForm(
            current_status=parcel.status,
        )

    return render(
        request,
        "parcels/update_parcel_status.html",
        {"parcel": parcel, "form": form},
    )