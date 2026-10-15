from django.contrib import admin
from .models import Complaint
from .models import Complaint, ComplaintHistory
# Register your models here.



@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "parcel",
        "category",
        "status",
        "assigned_agent",
        "created_at",
    )

    list_filter = ("status", "category", "created_at")

    search_fields = (
        "parcel__tracking_id",
        "description",
        "resolution_details",
    )

    readonly_fields = ("created_at", "updated_at")


@admin.register(ComplaintHistory)
class ComplaintHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )

    list_filter = ("old_status", "new_status", "created_at")
    search_fields = ("complaint__parcel__tracking_id", "note")
    readonly_fields = ("created_at",)