from django.test import TestCase
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from parcels.models import Parcel, ParcelHistory


User = get_user_model()


class CourierAnalyticsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="analytics_admin", password="TestPassword123!", role="ADMIN"
        )
        self.customer = User.objects.create_user(
            username="analytics_customer", password="TestPassword123!", role="CUSTOMER"
        )
        self.agent = User.objects.create_user(
            username="analytics_agent", password="TestPassword123!", role="AGENT"
        )
        self.superuser = User.objects.create_user(
            username="analytics_superuser",
            password="TestPassword123!",
            role="CUSTOMER",
            is_staff=True,
            is_superuser=True,
        )

    def make_parcel(self, **kwargs):
        data = {
            "sender_name": "Sender", "sender_phone": "9876543210",
            "receiver_name": "Receiver", "receiver_phone": "9876501234",
            "delivery_address": "Analytics address",
            "expected_delivery_date": timezone.localdate(),
            "created_by": self.admin,
        }
        data.update(kwargs)
        return Parcel.objects.create(**data)

    def test_only_admin_and_superuser_can_access_analytics(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("courier_analytics")).status_code, 200)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("courier_analytics")).status_code, 200)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("courier_analytics")).status_code, 403)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("courier_analytics")).status_code, 403)

    def test_parcel_status_analytics_match_records_and_delivery_events(self):
        delivered = self.make_parcel(assigned_agent=self.agent)
        Parcel.objects.filter(pk=delivered.pk).update(status=Parcel.Status.DELIVERED)
        ParcelHistory.objects.create(
            parcel=delivered,
            status=Parcel.Status.DELIVERED,
            new_status=Parcel.Status.DELIVERED,
            changed_by=self.agent,
        )
        registered = self.make_parcel()
        self.client.force_login(self.admin)

        response = self.client.get(reverse("courier_analytics"))

        self.assertEqual(response.context["parcel_status_counts"][Parcel.Status.DELIVERED], 1)
        self.assertEqual(response.context["parcel_status_counts"][Parcel.Status.REGISTERED], 1)
        self.assertEqual(response.context["on_time_count"], 1)
        self.assertEqual(response.context["late_count"], 0)
        self.assertContains(response, "Parcel status distribution")

    def test_date_filter_excludes_out_of_range_booking_and_custom_range_includes_it(self):
        old_parcel = self.make_parcel()
        Parcel.objects.filter(pk=old_parcel.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )
        recent_parcel = self.make_parcel()
        self.client.force_login(self.admin)

        recent = self.client.get(reverse("courier_analytics"), {"period": "7"})
        self.assertEqual(sum(recent.context["parcel_status_counts"].values()), 1)
        start = (timezone.localdate() - timedelta(days=45)).isoformat()
        end = (timezone.localdate() - timedelta(days=35)).isoformat()
        custom = self.client.get(
            reverse("courier_analytics"),
            {"period": "custom", "start_date": start, "end_date": end},
        )
        self.assertEqual(sum(custom.context["parcel_status_counts"].values()), 1)
        self.assertEqual(custom.context["start_date"].isoformat(), start)
        self.assertNotEqual(old_parcel.pk, recent_parcel.pk)

    def test_empty_analytics_dataset_renders_with_safe_empty_metrics(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("courier_analytics"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["parcel_status_total"], 0)
        self.assertIsNone(response.context["failure_rate"])
        self.assertIsNone(response.context["average_resolution_hours"])
        self.assertContains(response, "No parcels were booked")
