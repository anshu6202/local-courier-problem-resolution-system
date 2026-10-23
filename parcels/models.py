import uuid
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class Parcel(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Registered"
        IN_TRANSIT = "IN_TRANSIT", "In Transit"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Delivery Failed"
        SCHEDULED_FOR_RETRY = "SCHEDULED_FOR_RETRY", "Scheduled for Retry"
        RTO_INITIATED = "RTO_INITIATED", "Return to Origin"

    class FailureReason(models.TextChoices):
        CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE", "Customer unavailable"
        WRONG_ADDRESS = "WRONG_ADDRESS", "Wrong address"
        REJECTED = "REJECTED", "Rejected by recipient"
        OTHER = "OTHER", "Other"

    tracking_id = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
    )

    sender_name = models.CharField(max_length=100)
    sender_phone = models.CharField(max_length=15)
    receiver_name = models.CharField(max_length=100)
    receiver_phone = models.CharField(max_length=15)
    delivery_address = models.TextField()
    expected_delivery_date = models.DateField()
    delivered_to = models.CharField(max_length=100, blank=True)
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    delivery_otp = models.CharField(max_length=4, blank=True)
    delivery_otp_expires_at = models.DateTimeField(null=True, blank=True)
    delivery_otp_attempts = models.PositiveSmallIntegerField(default=0)
    package_weight = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    package_type = models.CharField(max_length=80, blank=True)
    failure_reason = models.CharField(
        max_length=30,
        choices=FailureReason.choices,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
    )

    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_parcels",
        limit_choices_to={"role": "AGENT", "is_active_agent": True},
    )

    # Populated only when we know when the parcel became unassigned. Existing
    # records are intentionally left NULL because their assignment history is unknown.
    unassigned_since = models.DateTimeField(null=True, blank=True, editable=False)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_parcels",
        limit_choices_to={"role": "CUSTOMER"},
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registered_parcels",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        assignment_changed = False
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values(
                "status", "assigned_agent_id"
            ).first()
            previous_status = previous["status"] if previous else None
            if previous_status and previous_status != self.status:
                raise ValidationError("Use transition_to() to change parcel status.")
            assignment_changed = bool(
                previous and previous["assigned_agent_id"] != self.assigned_agent_id
            )
        elif self.status != self.Status.REGISTERED:
            raise ValidationError("New parcels must start as registered.")
        if self.assigned_agent_id:
            self.unassigned_since = None
        elif not self.pk:
            self.unassigned_since = timezone.now()
        elif assignment_changed:
            self.unassigned_since = timezone.now()
        if not self.tracking_id:
            self.tracking_id = f"CR-{uuid.uuid4().hex[:10].upper()}"
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and (assignment_changed or self.assigned_agent_id):
            kwargs["update_fields"] = set(update_fields) | {"unassigned_since"}
        super().save(*args, **kwargs)
        # Assignment edits may come from app views, bulk operations, or Django admin.
        # Record only persisted changes; the model cannot infer the acting user.
        if assignment_changed:
            old_agent_id = previous["assigned_agent_id"]
            if old_agent_id is None:
                note = "Delivery agent assigned."
            elif self.assigned_agent_id is None:
                note = "Delivery agent unassigned."
            else:
                note = "Delivery agent reassigned."
            ParcelHistory.objects.create(
                parcel=self,
                status=self.status,
                old_status=self.status,
                new_status=self.status,
                note=note,
            )

    def transition_to(self, new_status, *, changed_by=None, note="", failure_reason="", delivered_to="", otp=""):
        allowed_transitions = {
            self.Status.REGISTERED: {self.Status.IN_TRANSIT},
            self.Status.SCHEDULED_FOR_RETRY: {self.Status.IN_TRANSIT},
            self.Status.IN_TRANSIT: {self.Status.DELIVERED, self.Status.FAILED},
        }
        if new_status not in allowed_transitions.get(self.status, set()):
            raise ValidationError(f"Cannot change parcel status from {self.status} to {new_status}.")
        if new_status == self.Status.FAILED and not failure_reason:
            raise ValidationError("A failure reason is required for failed deliveries.")
        if new_status == self.Status.DELIVERED and not delivered_to:
            raise ValidationError("Enter who received the parcel.")
        if new_status == self.Status.DELIVERED:
            if not self.delivery_otp or not self.delivery_otp_expires_at:
                raise ValidationError("No active delivery OTP exists. Request a new code.")
            if timezone.now() >= self.delivery_otp_expires_at:
                raise ValidationError("The delivery OTP has expired. Request a new code.")
            if self.delivery_otp_attempts >= 5:
                raise ValidationError("Too many OTP attempts. Request a new delivery code.")
            if not secrets.compare_digest(str(otp), self.delivery_otp):
                self.delivery_otp_attempts += 1
                self.save(update_fields=["delivery_otp_attempts"])
                raise ValidationError("The delivery OTP is incorrect.")

        old_status = self.status
        otp_value = f"{secrets.randbelow(10000):04d}" if new_status == self.Status.IN_TRANSIT else ""
        attempts = self.delivery_attempts + (1 if new_status == self.Status.FAILED else 0)
        final_status = new_status
        # Free-form notes are omitted from history so OTPs or other sensitive text
        # pasted into a delivery note cannot be persisted there.
        history_note = ""
        if new_status == self.Status.FAILED:
            if not failure_reason:
                raise ValidationError("A failure reason is required for failed deliveries.")
            final_status = (
                self.Status.RTO_INITIATED if attempts >= 3 else self.Status.SCHEDULED_FOR_RETRY
            )
            history_note = f"Delivery attempt {attempts} failed ({failure_reason})."
        with transaction.atomic():
            updated = type(self).objects.filter(pk=self.pk, status=old_status).update(
                status=final_status,
                delivery_attempts=attempts,
                failure_reason=failure_reason if new_status == self.Status.FAILED else "",
                delivered_to=delivered_to if new_status == self.Status.DELIVERED else self.delivered_to,
                delivery_otp="" if new_status == self.Status.DELIVERED else (otp_value or self.delivery_otp),
                delivery_otp_expires_at=None if new_status == self.Status.DELIVERED else (self.delivery_otp_expires_at if new_status != self.Status.IN_TRANSIT else timezone.now() + timedelta(minutes=15)),
                delivery_otp_attempts=0 if new_status in {self.Status.DELIVERED, self.Status.IN_TRANSIT} else self.delivery_otp_attempts,
            )
            if not updated:
                raise ValidationError("Parcel status was changed by another request. Reload and try again.")
            ParcelHistory.objects.create(
                parcel=self,
                old_status=old_status,
                new_status=final_status,
                status=final_status,
                changed_by=changed_by,
                note=history_note,
            )
            if new_status == self.Status.FAILED and attempts >= 3:
                from django.conf import settings
                from django.contrib.auth import get_user_model
                from django.core.mail import send_mail

                def notify_admins():
                    admin_emails = list(
                        get_user_model().objects.filter(
                            role="ADMIN", is_active=True
                        ).exclude(email="").values_list("email", flat=True)
                    )
                    if admin_emails:
                        send_mail(
                            f"Parcel RTO initiated: {self.tracking_id}",
                            f"Parcel {self.tracking_id} reached three failed delivery attempts.",
                            settings.DEFAULT_FROM_EMAIL,
                            admin_emails,
                            fail_silently=True,
                        )
                    elif settings.DEBUG:
                        import logging
                        logging.getLogger(__name__).warning(
                            "RTO initiated for parcel %s after three failed attempts.",
                            self.tracking_id,
                        )

                transaction.on_commit(notify_admins)
            if new_status == self.Status.IN_TRANSIT:
                from django.core.mail import send_mail
                from django.conf import settings
                customer = self.customer
                recipient_email = customer.email if customer and customer.email else ""
                if recipient_email:
                    transaction.on_commit(lambda: send_mail(
                        f"Parcelly delivery code for {self.tracking_id}",
                        f"Your delivery verification code is {otp_value}. It expires in 15 minutes.",
                        settings.DEFAULT_FROM_EMAIL,
                        [recipient_email],
                        fail_silently=True,
                    ))
                elif settings.DEBUG:
                    import logging
                    transaction.on_commit(lambda: logging.getLogger(__name__).warning(
                        "Delivery OTP for %s: %s", self.tracking_id, otp_value
                    ))
        self.status = final_status
        self.delivery_attempts = attempts
        self.failure_reason = failure_reason if new_status == self.Status.FAILED else ""
        if new_status == self.Status.DELIVERED:
            self.delivered_to = delivered_to
            self.delivery_otp = ""
            self.delivery_otp_expires_at = None

    def renew_delivery_otp(self, *, changed_by):
        if self.status != self.Status.IN_TRANSIT:
            raise ValidationError("A delivery code can only be renewed while the parcel is in transit.")
        otp_value = f"{secrets.randbelow(10000):04d}"
        expires_at = timezone.now() + timedelta(minutes=15)
        with transaction.atomic():
            updated = type(self).objects.filter(pk=self.pk, status=self.Status.IN_TRANSIT).update(
                delivery_otp=otp_value,
                delivery_otp_expires_at=expires_at,
                delivery_otp_attempts=0,
            )
            if not updated:
                raise ValidationError("Parcel status changed. Reload before requesting another code.")
            ParcelHistory.objects.create(
                parcel=self,
                old_status=self.Status.IN_TRANSIT,
                new_status=self.Status.IN_TRANSIT,
                status=self.Status.IN_TRANSIT,
                changed_by=changed_by,
                note="Delivery OTP renewed.",
            )
            from django.conf import settings
            from django.core.mail import send_mail
            recipient_email = self.customer.email if self.customer and self.customer.email else ""
            if recipient_email:
                transaction.on_commit(lambda: send_mail(
                    f"Parcelly delivery code for {self.tracking_id}",
                    f"Your new delivery verification code is {otp_value}. It expires in 15 minutes.",
                    settings.DEFAULT_FROM_EMAIL,
                    [recipient_email],
                    fail_silently=True,
                ))
            elif settings.DEBUG:
                import logging
                transaction.on_commit(lambda: logging.getLogger(__name__).warning(
                    "Delivery OTP for %s: %s", self.tracking_id, otp_value
                ))
        self.delivery_otp = otp_value
        self.delivery_otp_expires_at = expires_at
        self.delivery_otp_attempts = 0

    def __str__(self):
        return self.tracking_id


class ParcelHistory(models.Model):
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=20, choices=Parcel.Status.choices)
    old_status = models.CharField(max_length=20, choices=Parcel.Status.choices, blank=True)
    new_status = models.CharField(max_length=20, choices=Parcel.Status.choices, blank=True)
    note = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parcel_status_changes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.parcel.tracking_id} — {self.get_status_display()}"


class RedeliveryRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    parcel = models.ForeignKey(
        Parcel,
        on_delete=models.CASCADE,
        related_name="redelivery_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="redelivery_requests",
    )
    preferred_delivery_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    decision_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_redelivery_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["parcel"],
                condition=models.Q(status="PENDING"),
                name="one_pending_redelivery_per_parcel",
            ),
        ]

    def __str__(self):
        return f"Redelivery request for {self.parcel.tracking_id} ({self.get_status_display()})"
