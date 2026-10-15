
# Create your models here.
from django.conf import settings
from django.db import models


class Complaint(models.Model):

    class Category(models.TextChoices):
        LATE_DELIVERY = "LATE_DELIVERY", "Late Delivery"
        DAMAGED_PARCEL = "DAMAGED_PARCEL", "Damaged Parcel"
        WRONG_DELIVERY = "WRONG_DELIVERY", "Wrong Delivery"
        FAILED_DELIVERY = "FAILED_DELIVERY", "Failed Delivery"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        RESOLVED = "RESOLVED", "Resolved"

    parcel = models.ForeignKey(
        "parcels.Parcel",
        on_delete=models.CASCADE,
        related_name="complaints",
    )

    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reported_complaints",
    )

    category = models.CharField(
        max_length=20,
        choices=Category.choices,
    )

    description = models.TextField()

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.OPEN,
    )

    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_complaints",
        limit_choices_to={"role": "AGENT"},
    )

    resolution_details = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.parcel.tracking_id} - {self.get_category_display()}"

class ComplaintHistory(models.Model):
    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name="history",
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="complaint_history_changes",
    )

    old_status = models.CharField(
        max_length=15,
        choices=Complaint.Status.choices,
        blank=True,
    )

    new_status = models.CharField(
        max_length=15,
        choices=Complaint.Status.choices,
    )

    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Complaint #{self.complaint_id}: "
            f"{self.old_status} → {self.new_status}"
        )