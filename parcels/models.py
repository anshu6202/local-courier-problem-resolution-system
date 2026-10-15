from django.db import models

# Create your models here.
import uuid

from django.conf import settings
from django.db import models


class Parcel(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Registered"
        IN_TRANSIT = "IN_TRANSIT", "In Transit"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Delivery Failed"

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

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.REGISTERED,
    )

    assigned_agent = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="assigned_parcels",
    limit_choices_to={"role": "AGENT"},
)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registered_parcels",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.tracking_id:
            self.tracking_id = f"CR-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.tracking_id