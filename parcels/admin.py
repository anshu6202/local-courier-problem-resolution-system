from django.contrib import admin
from .models import Parcel


@admin.register(Parcel)
class ParcelAdmin(admin.ModelAdmin):
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
    readonly_fields = ("tracking_id", "created_at")
