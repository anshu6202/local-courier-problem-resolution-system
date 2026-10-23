from django.contrib import admin
from .models import Parcel, ParcelHistory


@admin.register(Parcel)
class ParcelAdmin(admin.ModelAdmin):
    change_form_template = "admin/parcels/parcel/change_form.html"
    list_display = (
        "tracking_id",
        "receiver_name",
        "status",
        "assigned_agent",
        "expected_delivery_date",
        "created_at",
    )

    list_filter = ("status", "expected_delivery_date")
    search_fields = (
        "tracking_id",
        "sender_name",
        "receiver_name",
        "receiver_phone",
    )

    list_editable = ("assigned_agent",)
    readonly_fields = ("tracking_id", "created_at", "status", "delivered_to", "failure_reason")

    def save_model(self, request, obj, form, change):
        old_agent_id = None
        if change:
            old_agent_id = Parcel.objects.filter(pk=obj.pk).values_list(
                "assigned_agent_id", flat=True
            ).first()
        super().save_model(request, obj, form, change)
        if not change:
            ParcelHistory.objects.create(
                parcel=obj,
                status=obj.status,
                new_status=obj.status,
                changed_by=request.user,
                note="Parcel registered",
            )
        elif old_agent_id != obj.assigned_agent_id:
            obj.history.filter(changed_by__isnull=True).order_by("-created_at").update(
                changed_by=request.user
            )


@admin.register(ParcelHistory)
class ParcelHistoryAdmin(admin.ModelAdmin):
    list_display = ("parcel", "old_status", "new_status", "changed_by", "timestamp")
    list_filter = ("status", "created_at")
    search_fields = ("parcel__tracking_id", "note")
    readonly_fields = ("created_at",)
