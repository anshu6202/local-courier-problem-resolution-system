
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta


def default_sla_deadline():
    return timezone.now() + timedelta(hours=24)


class Complaint(models.Model):

    class Category(models.TextChoices):
        LATE_DELIVERY = "LATE_DELIVERY", "Late Delivery"
        DAMAGED_PARCEL = "DAMAGED_PARCEL", "Damaged Parcel"
        WRONG_DELIVERY = "WRONG_DELIVERY", "Wrong Delivery"
        WRONG_ADDRESS = "WRONG_ADDRESS", "Wrong Address"
        RUDE_STAFF = "RUDE_STAFF", "Rude Staff"
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
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_complaints",
        limit_choices_to={"role": "CUSTOMER"},
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
        limit_choices_to={"role": "AGENT", "is_active_agent": True},
    )

    resolution_details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    sla_deadline = models.DateTimeField(default=default_sla_deadline, db_index=True)
    is_escalated = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parcel"],
                condition=Q(status__in=["OPEN", "IN_PROGRESS"]),
                name="one_active_complaint_per_parcel",
            ),
        ]

    @property
    def sla_time_label(self):
        remaining = self.sla_deadline - timezone.now()
        if remaining.total_seconds() <= 0:
            return "SLA breached"
        hours = max(1, int((remaining.total_seconds() + 3599) // 3600))
        return f"{hours} hour{'s' if hours != 1 else ''} left"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not self.pk and self.status != self.Status.OPEN:
            raise ValidationError("New complaints must start as open.")
        if self.pk:
            previous_status = type(self).objects.filter(pk=self.pk).values_list(
                "status", flat=True
            ).first()
            if previous_status and previous_status != self.status:
                raise ValidationError("Use transition_to() to change complaint status.")
        super().save(*args, **kwargs)
        if is_new:
            self.sla_deadline = self.created_at + timedelta(hours=24)
            type(self).objects.filter(pk=self.pk).update(sla_deadline=self.sla_deadline)

    def transition_to(self, new_status, *, changed_by, note=""):
        allowed_transitions = {
            self.Status.OPEN: {self.Status.IN_PROGRESS, self.Status.RESOLVED},
            self.Status.IN_PROGRESS: {self.Status.RESOLVED},
        }
        if new_status not in allowed_transitions.get(self.status, set()):
            raise ValidationError(f"Cannot change complaint status from {self.status} to {new_status}.")

        old_status = self.status
        resolved_at = timezone.now() if new_status == self.Status.RESOLVED else None
        with transaction.atomic():
            updated = type(self).objects.filter(pk=self.pk, status=old_status).update(
                status=new_status,
                resolved_at=resolved_at,
                updated_at=timezone.now(),
            )
            if not updated:
                raise ValidationError("Complaint status was changed by another request. Reload and try again.")
            ComplaintHistory.objects.create(
                complaint=self,
                changed_by=changed_by,
                old_status=old_status,
                new_status=new_status,
                note=note,
            )
        self.status = new_status
        self.resolved_at = resolved_at

    def __str__(self):
        return f"{self.parcel.tracking_id} - {self.get_category_display()}"

class ComplaintUpdate(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="complaint_updates")
    message = models.TextField()
    attachment = models.FileField(upload_to="complaint_attachments/", blank=True)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Update on complaint #{self.complaint_id}"


class ComplaintFeedback(models.Model):
    complaint = models.OneToOneField(
        Complaint,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5),
                name="complaint_feedback_rating_1_to_5",
            ),
        ]

    def __str__(self):
        return f"Feedback for complaint #{self.complaint_id}: {self.rating}/5"


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


class ComplaintNotification(models.Model):
    class Type(models.TextChoices):
        APPROACHING = "APPROACHING", "Approaching SLA"
        BREACHED = "BREACHED", "SLA breached"
        ESCALATED = "ESCALATED", "Complaint escalated"

    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="notifications"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="complaint_notifications",
    )
    notification_type = models.CharField(max_length=12, choices=Type.choices)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(
            fields=["complaint", "recipient", "notification_type"],
            name="unique_complaint_sla_notification",
        )]

    def __str__(self):
        return f"{self.get_notification_type_display()} for complaint {self.complaint_id}"
