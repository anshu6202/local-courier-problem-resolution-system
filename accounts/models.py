from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        AGENT = "AGENT", "Delivery Agent"
        CUSTOMER = "CUSTOMER", "Customer"

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )