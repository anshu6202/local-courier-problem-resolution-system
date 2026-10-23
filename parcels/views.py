from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.permissions import role_required

from .forms import (
    CustomerParcelBookingForm,
    ParcelForm,
    ParcelStatusUpdateForm,
    RedeliveryDecisionForm,
    RedeliveryRequestForm,
)
from .models import Parcel, ParcelHistory, RedeliveryRequest
from .delay_risk import assess_parcel_delay_risk


@role_required("ADMIN")
def parcel_create(request):
    if request.method == "POST":
        form = ParcelForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                parcel = form.save(commit=False)
                parcel.created_by = request.user
                parcel.save()
                ParcelHistory.objects.create(
                    parcel=parcel,
                    status=parcel.status,
                    new_status=parcel.status,
                    changed_by=request.user,
                    note="Parcel registered",
                )
            return render(request, "parcels/parcel_created.html", {"parcel": parcel})
    else:
        form = ParcelForm()
    return render(request, "parcels/parcel_form.html", {"form": form})


@role_required("CUSTOMER")
def customer_parcel_booking(request):
    if request.method == "POST":
        form = CustomerParcelBookingForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                parcel = form.save(commit=False)
                parcel.customer = request.user
                parcel.created_by = request.user
                parcel.save()
                ParcelHistory.objects.create(
                    parcel=parcel,
                    status=parcel.status,
                    new_status=parcel.status,
                    changed_by=request.user,
                    note="Parcel booked by customer",
                )
            return render(
                request,
                "parcels/customer_booking_confirmation.html",
                {"parcel": parcel},
            )
    else:
        form = CustomerParcelBookingForm()
    return render(request, "parcels/customer_booking_form.html", {"form": form})


@role_required("ADMIN")
def parcel_list(request):
    if request.method == "POST":
        if request.POST.get("bulk_assign") == "1":
            selected_ids = request.POST.getlist("parcel_ids")
            if not selected_ids:
                messages.error(request, "Select at least one parcel to update.")
                return redirect("admin_parcels")
            agent_id = request.POST.get("agent_id", "")
            agent = None
            if agent_id:
                agent = get_object_or_404(
                    get_user_model(),
                    pk=agent_id,
                    role="AGENT",
                    is_active=True,
                    is_active_agent=True,
                )
            with transaction.atomic():
                selected = list(Parcel.objects.filter(pk__in=selected_ids))
                updated_count = 0
                for item in selected:
                    if item.assigned_agent_id == (agent.pk if agent else None):
                        continue
                    item.assigned_agent = agent
                    item.save(update_fields=["assigned_agent"])
                    event = item.history.filter(changed_by__isnull=True).order_by("-created_at").first()
                    if event:
                        event.changed_by = request.user
                        event.save(update_fields=["changed_by"])
                    updated_count += 1
            messages.success(request, f"Updated assignment for {updated_count} parcel(s).")
            return redirect("admin_parcels")

        parcel = get_object_or_404(Parcel, pk=request.POST.get("parcel_id"))
        agent_id = request.POST.get("agent_id", "")
        agent = None
        if agent_id:
            agent = get_object_or_404(
                get_user_model(),
                pk=agent_id,
                role="AGENT",
                is_active=True,
                is_active_agent=True,
            )
        with transaction.atomic():
            old_agent_id = parcel.assigned_agent_id
            parcel.assigned_agent = agent
            parcel.save(update_fields=["assigned_agent"])
            if old_agent_id != parcel.assigned_agent_id:
                event = parcel.history.filter(changed_by__isnull=True).order_by("-created_at").first()
                if event:
                    event.changed_by = request.user
                    event.save(update_fields=["changed_by"])
        messages.success(request, f"Assignment updated for {parcel.tracking_id}.")
        return redirect("admin_parcels")

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    unassigned_only = request.GET.get("unassigned") == "1"
    parcels = Parcel.objects.select_related("customer", "assigned_agent").order_by("-created_at")
    if query:
        parcels = parcels.filter(
            Q(tracking_id__icontains=query)
            | Q(receiver_name__icontains=query)
            | Q(receiver_phone__icontains=query)
        )
    if status in Parcel.Status.values:
        parcels = parcels.filter(status=status)
    if unassigned_only:
        parcels = parcels.filter(assigned_agent__isnull=True)

    page = Paginator(parcels, 20).get_page(request.GET.get("page"))
    agents = get_user_model().objects.filter(
        role="AGENT", is_active=True, is_active_agent=True
    )
    return render(
        request,
        "parcels/parcel_list.html",
        {
            "parcels": page,
            "page_obj": page,
            "query": query,
            "selected_status": status,
            "unassigned_only": unassigned_only,
            "statuses": Parcel.Status.choices,
            "agents": agents,
        },
    )


def parcel_track(request):
    user = request.user
    is_admin = user.is_authenticated and (
        user.is_superuser or getattr(user, "role", None) == "ADMIN"
    )
    is_customer = user.is_authenticated and getattr(user, "role", None) == "CUSTOMER"
    is_agent = user.is_authenticated and getattr(user, "role", None) == "AGENT"
    is_public_tracking = not user.is_authenticated

    if user.is_authenticated and not (is_admin or is_customer or is_agent):
        return HttpResponseForbidden("You cannot access parcel tracking.")

    tracking_id = request.GET.get("tracking_id", "").strip()
    parcel = None
    delay_assessment = None
    searched = bool(tracking_id)
    if searched:
        parcels = Parcel.objects.all()
        if is_customer:
            parcels = parcels.filter(customer=user)
        elif is_agent:
            parcels = parcels.filter(assigned_agent=user)
        parcel = parcels.filter(tracking_id__iexact=tracking_id).prefetch_related("history").first()
        if parcel and is_customer:
            delay_assessment = assess_parcel_delay_risk(parcel)
    return render(
        request,
        "parcels/parcel_track.html",
        {
            "parcel": parcel,
            "searched": searched,
            "tracking_id": tracking_id,
            "public_tracking": is_public_tracking,
            "delay_assessment": delay_assessment,
        },
    )


@role_required("CUSTOMER")
def customer_parcels(request):
    parcels = Parcel.objects.filter(customer=request.user).select_related(
        "assigned_agent"
    ).order_by("-created_at")
    redelivery_requests = RedeliveryRequest.objects.filter(
        requested_by=request.user
    ).select_related("parcel", "reviewed_by")
    pending_request_parcel_ids = set(
        redelivery_requests.filter(status=RedeliveryRequest.Status.PENDING)
        .values_list("parcel_id", flat=True)
    )
    return render(
        request,
        "parcels/customer_parcels.html",
        {
            "parcels": parcels,
            "redelivery_requests": redelivery_requests,
            "pending_request_parcel_ids": pending_request_parcel_ids,
        },
    )


@role_required("CUSTOMER")
def customer_redelivery_request(request, tracking_id):
    parcel = get_object_or_404(
        Parcel,
        tracking_id=tracking_id,
        customer=request.user,
        status=Parcel.Status.SCHEDULED_FOR_RETRY,
        delivery_attempts__lt=3,
    )
    if RedeliveryRequest.objects.filter(
        parcel=parcel,
        status=RedeliveryRequest.Status.PENDING,
    ).exists():
        messages.info(request, "A redelivery request is already pending for this parcel.")
        return redirect("customer_shipments")

    if request.method == "POST":
        form = RedeliveryRequestForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    redelivery_request = RedeliveryRequest.objects.create(
                        parcel=parcel,
                        requested_by=request.user,
                        preferred_delivery_date=form.cleaned_data[
                            "preferred_delivery_date"
                        ],
                        reason=form.cleaned_data["reason"].strip(),
                    )
                    ParcelHistory.objects.create(
                        parcel=parcel,
                        status=parcel.status,
                        old_status=parcel.status,
                        new_status=parcel.status,
                        changed_by=request.user,
                        note=(
                            "Customer requested redelivery for "
                            f"{redelivery_request.preferred_delivery_date:%Y-%m-%d}."
                        ),
                    )
            except IntegrityError:
                messages.info(request, "A redelivery request is already pending for this parcel.")
                return redirect("customer_shipments")
            messages.success(request, "Your redelivery request was sent for review.")
            return redirect("customer_shipments")
    else:
        form = RedeliveryRequestForm()

    return render(
        request,
        "parcels/redelivery_request_form.html",
        {"parcel": parcel, "form": form},
    )


@role_required("ADMIN")
def admin_redelivery_requests(request):
    form_errors = {}
    if request.method == "POST":
        try:
            request_id = int(request.POST.get("request_id", ""))
        except (TypeError, ValueError):
            messages.error(request, "Select a valid redelivery request to review.")
            return redirect("admin_redelivery_requests")
        decision_form = RedeliveryDecisionForm(request.POST, prefix=str(request_id))
        if decision_form.is_valid():
            with transaction.atomic():
                redelivery_request = (
                    RedeliveryRequest.objects.select_for_update()
                    .filter(pk=request_id, status=RedeliveryRequest.Status.PENDING)
                    .first()
                )
                if redelivery_request is None:
                    messages.error(request, "This request is no longer pending review.")
                    return redirect("admin_redelivery_requests")

                parcel = Parcel.objects.select_for_update().get(
                    pk=redelivery_request.parcel_id
                )
                decision = decision_form.cleaned_data["decision"]
                decision_note = decision_form.cleaned_data["decision_note"].strip()
                if decision == RedeliveryRequest.Status.APPROVED:
                    if (
                        parcel.status != Parcel.Status.SCHEDULED_FOR_RETRY
                        or parcel.delivery_attempts >= 3
                    ):
                        decision_form.add_error(
                            None,
                            "This parcel is no longer eligible for redelivery approval.",
                        )
                    elif redelivery_request.preferred_delivery_date < timezone.localdate():
                        decision_form.add_error(
                            None,
                            "The preferred date has passed. Reject this request and ask the customer to submit a new date.",
                        )
                    else:
                        assigned_agent = decision_form.cleaned_data["assigned_agent"]
                        parcel.expected_delivery_date = (
                            redelivery_request.preferred_delivery_date
                        )
                        if assigned_agent:
                            parcel.assigned_agent = assigned_agent
                        parcel.save(
                            update_fields=["expected_delivery_date", "assigned_agent"]
                        )
                        redelivery_request.status = RedeliveryRequest.Status.APPROVED
                        redelivery_request.decision_note = decision_note
                        history_note = (
                            "Admin approved redelivery for "
                            f"{parcel.expected_delivery_date:%Y-%m-%d}."
                        )
                        if assigned_agent:
                            history_note += f" Assigned agent: {assigned_agent.username}."
                        ParcelHistory.objects.create(
                            parcel=parcel,
                            status=parcel.status,
                            old_status=parcel.status,
                            new_status=parcel.status,
                            changed_by=request.user,
                            note=history_note[:255],
                        )
                else:
                    redelivery_request.status = RedeliveryRequest.Status.REJECTED
                    redelivery_request.decision_note = decision_note
                    ParcelHistory.objects.create(
                        parcel=parcel,
                        status=parcel.status,
                        old_status=parcel.status,
                        new_status=parcel.status,
                        changed_by=request.user,
                        note="Admin rejected redelivery request.",
                    )

                if not decision_form.errors:
                    redelivery_request.reviewed_by = request.user
                    redelivery_request.reviewed_at = timezone.now()
                    redelivery_request.save(
                        update_fields=[
                            "status",
                            "decision_note",
                            "reviewed_by",
                            "reviewed_at",
                        ]
                    )
                    messages.success(
                        request,
                        "Redelivery request "
                        + ("approved." if decision == "APPROVED" else "rejected."),
                    )
                    return redirect("admin_redelivery_requests")
            form_errors[str(request_id)] = decision_form

    requests = RedeliveryRequest.objects.select_related(
        "parcel", "requested_by", "reviewed_by", "parcel__assigned_agent"
    ).order_by("status", "-created_at")
    rows = [
        {
            "redelivery_request": redelivery_request,
            "form": form_errors.get(
                str(redelivery_request.pk),
                RedeliveryDecisionForm(prefix=str(redelivery_request.pk)),
            ),
        }
        for redelivery_request in requests
    ]
    return render(request, "parcels/admin_redelivery_requests.html", {"rows": rows})


@role_required("AGENT")
def agent_parcels(request):
    parcels = Parcel.objects.filter(assigned_agent=request.user).order_by("-created_at")
    return render(request, "parcels/agent_parcels.html", {"parcels": parcels})


@role_required("AGENT")
def update_parcel_status(request, tracking_id):
    parcel = get_object_or_404(
        Parcel,
        tracking_id=tracking_id,
        assigned_agent=request.user,
    )
    if parcel.status not in {
        Parcel.Status.REGISTERED,
        Parcel.Status.IN_TRANSIT,
        Parcel.Status.SCHEDULED_FOR_RETRY,
    }:
        messages.error(request, "This parcel can no longer be updated.")
        return redirect("agent_deliveries")

    if request.method == "POST":
        if request.POST.get("action") == "renew_otp":
            try:
                parcel.renew_delivery_otp(changed_by=request.user)
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, "A new 15-minute delivery OTP has been sent or logged.")
            return redirect("update_parcel_status", tracking_id=parcel.tracking_id)
        form = ParcelStatusUpdateForm(request.POST, current_status=parcel.status)
        if form.is_valid():
            try:
                parcel.transition_to(
                    form.cleaned_data["status"],
                    changed_by=request.user,
                    note=form.cleaned_data["note"],
                    failure_reason=form.cleaned_data["failure_reason"],
                    delivered_to=form.cleaned_data["delivered_to"].strip(),
                    otp=form.cleaned_data["otp"],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, f"Parcel {parcel.tracking_id} status updated.")
                return redirect("agent_deliveries")
    else:
        form = ParcelStatusUpdateForm(current_status=parcel.status)

    return render(
        request,
        "parcels/update_parcel_status.html",
        {"parcel": parcel, "form": form},
    )


@role_required("ADMIN", "AGENT")
def shipping_label(request, tracking_id):
    parcel = get_object_or_404(Parcel.objects.select_related("assigned_agent"), tracking_id=tracking_id)
    if request.user.role == "AGENT" and parcel.assigned_agent_id != request.user.id:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("This parcel is not assigned to you.")

    from reportlab.lib.pagesizes import A6
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    import barcode
    from barcode.writer import ImageWriter
    from io import BytesIO

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{parcel.tracking_id}-label.pdf"'
    pdf = canvas.Canvas(response, pagesize=A6)
    width, height = A6
    left = 8 * mm
    y = height - 12 * mm
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(left, y, "PARCELLY")
    y -= 10 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(left, y, "TRACKING NUMBER")
    y -= 6 * mm
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(left, y, parcel.tracking_id)
    y -= 8 * mm
    barcode_buffer = BytesIO()
    barcode.get("code128", parcel.tracking_id, writer=ImageWriter()).write(
        barcode_buffer,
        {"module_height": 12, "module_width": 0.25, "write_text": False},
    )
    barcode_buffer.seek(0)
    pdf.drawImage(ImageReader(barcode_buffer), left, y - 18 * mm, width=88 * mm, height=18 * mm, preserveAspectRatio=True, anchor="sw")
    y -= 25 * mm

    def draw_block(title, lines):
        nonlocal y
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(left, y, title)
        y -= 5 * mm
        pdf.setFont("Helvetica", 8)
        for line in lines:
            for start in range(0, len(line), 42):
                pdf.drawString(left, y, line[start:start + 42])
                y -= 4 * mm
        y -= 2 * mm

    draw_block("FROM", [parcel.sender_name, parcel.sender_phone])
    draw_block("DELIVER TO", [parcel.receiver_name, parcel.receiver_phone, parcel.delivery_address])
    pdf.setFont("Helvetica", 8)
    pdf.drawString(left, y, f"Booked: {parcel.created_at:%d %b %Y}")
    pdf.drawRightString(width - left, y, f"{parcel.package_weight or '—'} kg")
    y -= 5 * mm
    pdf.drawString(left, y, f"Package: {parcel.package_type or 'Standard'}")
    pdf.showPage()
    pdf.save()
    return response
