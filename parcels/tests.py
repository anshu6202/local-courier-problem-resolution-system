from django.test import TestCase

# Create your tests here.

from datetime import date

from django.contrib.auth import get_user_model

from .models import Parcel


User = get_user_model()


class ParcelModelTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username="testadmin",
            password="TestPassword123!",
            role="ADMIN",
        )

    def test_parcel_tracking_id_is_generated(self):
        parcel = Parcel.objects.create(
            sender_name="Test Sender",
            sender_phone="9876543210",
            receiver_name="Test Receiver",
            receiver_phone="9876501234",
            delivery_address="Test Delivery Address",
            expected_delivery_date=date(2026, 11, 1),
            created_by=self.admin,
        )

        self.assertTrue(parcel.tracking_id)
        self.assertTrue(parcel.tracking_id.startswith("CR-"))

    def test_tracking_id_is_unique(self):
        first_parcel = Parcel.objects.create(
            sender_name="Sender One",
            sender_phone="9876543210",
            receiver_name="Receiver One",
            receiver_phone="9876501234",
            delivery_address="Address One",
            expected_delivery_date=date(2026, 11, 1),
            created_by=self.admin,
        )

        second_parcel = Parcel.objects.create(
            sender_name="Sender Two",
            sender_phone="9876543211",
            receiver_name="Receiver Two",
            receiver_phone="9876501235",
            delivery_address="Address Two",
            expected_delivery_date=date(2026, 11, 2),
            created_by=self.admin,
        )

        self.assertNotEqual(
            first_parcel.tracking_id,
            second_parcel.tracking_id,
        )
