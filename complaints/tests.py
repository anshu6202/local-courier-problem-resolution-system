from django.test import TestCase

# Create your tests here.

from datetime import date

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from parcels.models import Parcel
from .models import Complaint

User = get_user_model()


class ComplaintTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username="testadmin",
            password="TestPassword123!",
            role="ADMIN",
        )

        self.customer = User.objects.create_user(
            username="testcustomer",
            password="TestPassword123!",
            role="CUSTOMER",
        )

        self.parcel = Parcel.objects.create(
            sender_name="Test Sender",
            sender_phone="9876543210",
            receiver_name="Test Receiver",
            receiver_phone="9876501234",
            delivery_address="Test Address",
            expected_delivery_date=date(2026, 11, 1),
            created_by=self.admin,
        )

    def test_complaint_default_status_is_open(self):
        complaint = Complaint.objects.create(
            parcel=self.parcel,
            reported_by=self.customer,
            category=Complaint.Category.LATE_DELIVERY,
            description="Parcel has not arrived on time.",
        )

        self.assertEqual(
            complaint.status,
            Complaint.Status.OPEN,
        )

    def test_complaint_is_linked_to_correct_parcel(self):
        complaint = Complaint.objects.create(
            parcel=self.parcel,
            reported_by=self.customer,
            category=Complaint.Category.OTHER,
            description="Please check my parcel.",
        )

        self.assertEqual(complaint.parcel, self.parcel)

    def test_complaint_has_reporter(self):
        complaint = Complaint.objects.create(
            parcel=self.parcel,
            reported_by=self.customer,
            category=Complaint.Category.DAMAGED_PARCEL,
            description="Parcel arrived damaged.",
        )

        self.assertEqual(complaint.reported_by, self.customer)
