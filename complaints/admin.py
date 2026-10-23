from django.contrib import admin
from .models import Complaint, ComplaintFeedback, ComplaintHistory, ComplaintUpdate
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

    readonly_fields = ("status", "resolved_at", "created_at", "updated_at")


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


@admin.register(ComplaintUpdate)
class ComplaintUpdateAdmin(admin.ModelAdmin):
    list_display = ("complaint", "author", "is_internal", "created_at")
    search_fields = ("complaint__parcel__tracking_id", "author__username", "message")
    readonly_fields = ("created_at",)


@admin.register(ComplaintFeedback)
class ComplaintFeedbackAdmin(admin.ModelAdmin):
    list_display = ("complaint", "rating", "submitted_at")
    list_filter = ("rating", "submitted_at")
    search_fields = ("complaint__parcel__tracking_id", "comment")
    readonly_fields = ("submitted_at",)
