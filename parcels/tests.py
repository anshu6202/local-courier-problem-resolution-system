from django.test import TestCase

# Create your tests here.

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.test import override_settings

from .models import Parcel, ParcelHistory, RedeliveryRequest
from .delay_risk import assess_parcel_delay_risk


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


class ParcelTrackingAccessTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="tracking_customer",
            password="TestPassword123!",
            role="CUSTOMER",
        )
        self.other_customer = User.objects.create_user(
            username="other_customer",
            password="TestPassword123!",
            role="CUSTOMER",
        )
        self.admin = User.objects.create_user(
            username="tracking_admin",
            password="TestPassword123!",
            role="ADMIN",
        )
        self.agent = User.objects.create_user(
            username="tracking_agent",
            password="TestPassword123!",
            role="AGENT",
        )
        self.other_agent = User.objects.create_user(
            username="other_agent",
            password="TestPassword123!",
            role="AGENT",
        )
        self.customer_parcel = self.create_parcel(
            customer=self.customer,
            created_by=self.customer,
            assigned_agent=self.agent,
            sender_name="Customer Sender",
            sender_phone="1111111111",
            receiver_name="Customer Receiver",
            receiver_phone="2222222222",
            delivery_address="Customer Private Address",
        )
        self.other_parcel = self.create_parcel(
            customer=self.other_customer,
            created_by=self.other_customer,
            assigned_agent=self.other_agent,
            sender_name="Other Sender",
            sender_phone="3333333333",
            receiver_name="Other Receiver",
            receiver_phone="4444444444",
            delivery_address="Other Private Address",
        )

    def create_parcel(self, **kwargs):
        defaults = {
            "sender_name": "Sender",
            "sender_phone": "9876543210",
            "receiver_name": "Receiver",
            "receiver_phone": "9876501234",
            "delivery_address": "Test address",
            "expected_delivery_date": timezone.localdate() + timedelta(days=2),
        }
        defaults.update(kwargs)
        return Parcel.objects.create(**defaults)

    def tracking_url(self, parcel):
        return f"{reverse('public_parcel_track')}?tracking_id={parcel.tracking_id}"

    def test_customer_can_track_own_parcel_but_not_another_customers(self):
        self.client.force_login(self.customer)

        own_response = self.client.get(self.tracking_url(self.customer_parcel))
        other_response = self.client.get(self.tracking_url(self.other_parcel))

        self.assertEqual(own_response.status_code, 200)
        self.assertContains(own_response, "Customer Private Address")
        self.assertEqual(other_response.status_code, 200)
        self.assertIsNone(other_response.context["parcel"])
        self.assertNotContains(other_response, "Other Private Address")

    def test_admin_can_track_any_parcel(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.tracking_url(self.other_parcel))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Other Private Address")

    def test_agent_can_track_only_assigned_parcels(self):
        ParcelHistory.objects.create(
            parcel=self.customer_parcel,
            status=self.customer_parcel.status,
            note="Parcel registered",
        )
        self.client.force_login(self.agent)

        response = self.client.get(self.tracking_url(self.customer_parcel))
        denied_response = self.client.get(self.tracking_url(self.other_parcel))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tracking history")
        self.assertEqual(denied_response.status_code, 200)
        self.assertIsNone(denied_response.context["parcel"])

    def test_assignment_and_reassignment_are_recorded_once(self):
        parcel = self.create_parcel(customer=self.customer, created_by=self.customer)
        parcel.assigned_agent = self.agent
        parcel.save(update_fields=["assigned_agent"])
        parcel.refresh_from_db()
        parcel.assigned_agent = self.other_agent
        parcel.save(update_fields=["assigned_agent"])
        parcel.refresh_from_db()
        parcel.assigned_agent = None
        parcel.save(update_fields=["assigned_agent"])

        self.assertEqual(
            list(parcel.history.values_list("note", flat=True)),
            ["Delivery agent assigned.", "Delivery agent reassigned.", "Delivery agent unassigned."],
        )

    def test_agent_keeps_assigned_deliveries_and_cannot_open_other_agent_update(self):
        self.client.force_login(self.agent)

        deliveries_response = self.client.get(reverse("agent_deliveries"))
        other_update_response = self.client.get(
            reverse(
                "update_parcel_status",
                kwargs={"tracking_id": self.other_parcel.tracking_id},
            )
        )

        self.assertEqual(deliveries_response.status_code, 200)
        self.assertContains(deliveries_response, self.customer_parcel.tracking_id)
        self.assertNotContains(deliveries_response, self.other_parcel.tracking_id)
        self.assertEqual(other_update_response.status_code, 404)

    def test_anonymous_tracking_does_not_show_private_parcel_information(self):
        response = self.client.get(self.tracking_url(self.customer_parcel))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Customer Sender")
        self.assertNotContains(response, "Customer Receiver")
        self.assertNotContains(response, "Customer Private Address")
        self.assertNotContains(response, "1111111111")
        self.assertNotContains(response, "2222222222")


class RedeliveryRequestTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="redelivery_customer",
            password="TestPassword123!",
            role="CUSTOMER",
        )
        self.other_customer = User.objects.create_user(
            username="redelivery_other_customer",
            password="TestPassword123!",
            role="CUSTOMER",
        )
        self.admin = User.objects.create_user(
            username="redelivery_admin",
            password="TestPassword123!",
            role="ADMIN",
        )
        self.agent = User.objects.create_user(
            username="redelivery_agent",
            password="TestPassword123!",
            role="AGENT",
            is_active_agent=True,
        )
        self.parcel = Parcel.objects.create(
            sender_name="Sender",
            sender_phone="9876543210",
            receiver_name="Receiver",
            receiver_phone="9876501234",
            delivery_address="Delivery address",
            expected_delivery_date=timezone.localdate() + timedelta(days=1),
            customer=self.customer,
            created_by=self.customer,
        )
        Parcel.objects.filter(pk=self.parcel.pk).update(
            status=Parcel.Status.SCHEDULED_FOR_RETRY,
            delivery_attempts=1,
        )
        self.parcel.refresh_from_db()

    def request_url(self):
        return reverse(
            "customer_redelivery_request",
            kwargs={"tracking_id": self.parcel.tracking_id},
        )

    def create_pending_request(self, **kwargs):
        return RedeliveryRequest.objects.create(
            parcel=self.parcel,
            requested_by=self.customer,
            preferred_delivery_date=timezone.localdate() + timedelta(days=4),
            **kwargs,
        )

    def post_admin_decision(self, redelivery_request, decision, **extra):
        payload = {
            "request_id": str(redelivery_request.pk),
            f"{redelivery_request.pk}-decision": decision,
            f"{redelivery_request.pk}-assigned_agent": "",
            f"{redelivery_request.pk}-decision_note": "",
        }
        payload.update(
            {
                f"{redelivery_request.pk}-{key}": value
                for key, value in extra.items()
            }
        )
        return self.client.post(reverse("admin_redelivery_requests"), payload)

    def test_customer_can_request_redelivery_for_own_retry_parcel(self):
        self.client.force_login(self.customer)

        get_response = self.client.get(self.request_url())
        post_response = self.client.post(
            self.request_url(),
            {
                "preferred_delivery_date": (
                    timezone.localdate() + timedelta(days=3)
                ).isoformat(),
                "reason": "Please deliver after 5 PM.",
            },
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertRedirects(post_response, reverse("customer_shipments"))
        redelivery_request = RedeliveryRequest.objects.get(parcel=self.parcel)
        self.assertEqual(redelivery_request.requested_by, self.customer)
        self.assertEqual(redelivery_request.status, RedeliveryRequest.Status.PENDING)
        self.assertTrue(
            ParcelHistory.objects.filter(
                parcel=self.parcel,
                note__contains="Customer requested redelivery",
            ).exists()
        )
        self.assertContains(
            self.client.get(reverse("customer_shipments")),
            "Pending review",
        )

    def test_admin_can_view_pending_request_queue(self):
        self.create_pending_request()
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_redelivery_requests"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.parcel.tracking_id)
        self.assertContains(response, "Save decision")

    def test_customer_cannot_request_redelivery_for_another_customers_parcel(self):
        self.client.force_login(self.other_customer)

        response = self.client.get(self.request_url())

        self.assertEqual(response.status_code, 404)

    def test_past_preferred_date_is_rejected(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            self.request_url(),
            {
                "preferred_delivery_date": (
                    timezone.localdate() - timedelta(days=1)
                ).isoformat(),
                "reason": "Past date should fail.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(RedeliveryRequest.objects.exists())
        self.assertIn(
            "Preferred redelivery date cannot be in the past.",
            response.context["form"].errors["preferred_delivery_date"],
        )

    def test_duplicate_pending_request_is_prevented(self):
        self.create_pending_request()
        self.client.force_login(self.customer)

        response = self.client.post(
            self.request_url(),
            {
                "preferred_delivery_date": (
                    timezone.localdate() + timedelta(days=5)
                ).isoformat(),
            },
        )

        self.assertRedirects(response, reverse("customer_shipments"))
        self.assertEqual(RedeliveryRequest.objects.filter(parcel=self.parcel).count(), 1)

    def test_admin_approval_sets_date_assignment_and_history_for_retry(self):
        redelivery_request = self.create_pending_request()
        self.client.force_login(self.admin)

        response = self.post_admin_decision(
            redelivery_request,
            "APPROVED",
            assigned_agent=str(self.agent.pk),
            decision_note="Approved for the requested date.",
        )

        self.assertRedirects(response, reverse("admin_redelivery_requests"))


        redelivery_request.refresh_from_db()
        self.parcel.refresh_from_db()
        self.assertEqual(redelivery_request.status, RedeliveryRequest.Status.APPROVED)
        self.assertEqual(redelivery_request.reviewed_by, self.admin)
        self.assertEqual(
            self.parcel.expected_delivery_date,
            redelivery_request.preferred_delivery_date,
        )
        self.assertEqual(self.parcel.assigned_agent, self.agent)
        self.assertEqual(self.parcel.status, Parcel.Status.SCHEDULED_FOR_RETRY)
        self.assertTrue(
            ParcelHistory.objects.filter(
                parcel=self.parcel,
                note__contains="Admin approved redelivery",
            ).exists()
        )

    def test_admin_rejection_is_saved_and_visible_to_customer(self):
        redelivery_request = self.create_pending_request()
        self.client.force_login(self.admin)

        response = self.post_admin_decision(
            redelivery_request,
            "REJECTED",
            decision_note="Please confirm the address first.",
        )

        self.assertRedirects(response, reverse("admin_redelivery_requests"))
        redelivery_request.refresh_from_db()
        self.assertEqual(redelivery_request.status, RedeliveryRequest.Status.REJECTED)
        self.assertEqual(redelivery_request.reviewed_by, self.admin)
        self.assertEqual(
            redelivery_request.decision_note,
            "Please confirm the address first.",
        )
        self.assertTrue(
            ParcelHistory.objects.filter(
                parcel=self.parcel,
                note__contains="Admin rejected redelivery request",
            ).exists()
        )

        self.client.force_login(self.customer)
        customer_response = self.client.get(reverse("customer_shipments"))
        self.assertContains(customer_response, "Rejected")
        self.assertContains(customer_response, "Please confirm the address first.")

    def test_non_customer_and_non_admin_roles_are_denied(self):
        self.client.force_login(self.agent)
        customer_endpoint = self.client.get(self.request_url())
        admin_endpoint = self.client.get(reverse("admin_redelivery_requests"))

        self.assertEqual(customer_endpoint.status_code, 403)
        self.assertEqual(admin_endpoint.status_code, 403)

        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(reverse("admin_redelivery_requests")).status_code,
            403,
        )

    def test_admin_cannot_approve_if_retry_parcel_has_left_retry_queue(self):
        redelivery_request = self.create_pending_request()
        Parcel.objects.filter(pk=self.parcel.pk).update(status=Parcel.Status.IN_TRANSIT)
        self.client.force_login(self.admin)

        response = self.post_admin_decision(redelivery_request, "APPROVED")

        self.assertEqual(response.status_code, 200)
        redelivery_request.refresh_from_db()
        self.assertEqual(redelivery_request.status, RedeliveryRequest.Status.PENDING)
        self.assertContains(response, "no longer eligible for redelivery approval")

    def test_admin_decision_rejects_malformed_request_id(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin_redelivery_requests"),
            {"request_id": "not-an-id"},
        )

        self.assertRedirects(response, reverse("admin_redelivery_requests"))


class ParcelDelayRiskTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="risk_admin", password="TestPassword123!", role="ADMIN"
        )
        self.customer = User.objects.create_user(
            username="risk_customer", password="TestPassword123!", role="CUSTOMER"
        )
        self.agent = User.objects.create_user(
            username="risk_agent", password="TestPassword123!", role="AGENT"
        )

    def make_parcel(self, **kwargs):
        values = {
            "sender_name": "Sender", "sender_phone": "9876543210",
            "receiver_name": "Receiver", "receiver_phone": "9876501234",
            "delivery_address": "Private address",
            "expected_delivery_date": timezone.localdate() + timedelta(days=10),
            "created_by": self.customer, "customer": self.customer,
        }
        values.update(kwargs)
        return Parcel.objects.create(**values)

    def test_assignment_changes_start_and_clear_the_known_unassigned_clock(self):
        parcel = self.make_parcel()
        self.assertIsNotNone(parcel.unassigned_since)
        parcel.assigned_agent = self.agent
        parcel.save(update_fields=["assigned_agent"])
        parcel.refresh_from_db()
        self.assertIsNone(parcel.unassigned_since)
        parcel.assigned_agent = None
        parcel.save(update_fields=["assigned_agent"])
        parcel.refresh_from_db()
        self.assertIsNotNone(parcel.unassigned_since)

    def test_overdue_active_parcel_is_high_risk_but_closed_parcels_are_excluded(self):
        overdue = self.make_parcel(
            expected_delivery_date=timezone.localdate() - timedelta(days=1)
        )
        self.assertEqual(assess_parcel_delay_risk(overdue)["level"], "HIGH")
        for status in (Parcel.Status.DELIVERED, Parcel.Status.RTO_INITIATED):
            closed = self.make_parcel(expected_delivery_date=timezone.localdate() - timedelta(days=5))
            Parcel.objects.filter(pk=closed.pk).update(status=status)
            closed.refresh_from_db()
            self.assertEqual(
                assess_parcel_delay_risk(closed)["level"], "NO_CURRENT_RISK"
            )

    @override_settings(PARCEL_UNASSIGNED_RISK_HOURS=24)
    def test_unassigned_warning_uses_recorded_assignment_age_only(self):
        parcel = self.make_parcel()
        Parcel.objects.filter(pk=parcel.pk).update(
            unassigned_since=timezone.now() - timedelta(hours=25)
        )
        parcel.refresh_from_db()
        self.assertEqual(assess_parcel_delay_risk(parcel)["level"], "MEDIUM")
        parcel.unassigned_since = None
        self.assertEqual(assess_parcel_delay_risk(parcel)["level"], "NO_CURRENT_RISK")

    @override_settings(PARCEL_LONG_TRANSIT_RISK_HOURS=48)
    def test_long_transit_uses_in_transit_history_not_parcel_creation(self):
        parcel = self.make_parcel()
        Parcel.objects.filter(pk=parcel.pk).update(status=Parcel.Status.IN_TRANSIT)
        parcel.refresh_from_db()
        self.assertEqual(assess_parcel_delay_risk(parcel)["level"], "NO_CURRENT_RISK")
        event = ParcelHistory.objects.create(
            parcel=parcel,
            status=Parcel.Status.IN_TRANSIT,
            new_status=Parcel.Status.IN_TRANSIT,
        )
        ParcelHistory.objects.filter(pk=event.pk).update(
            created_at=timezone.now() - timedelta(hours=50)
        )
        parcel = Parcel.objects.prefetch_related("history").get(pk=parcel.pk)
        self.assertEqual(assess_parcel_delay_risk(parcel)["level"], "HIGH")

    def test_failed_attempts_raise_risk_and_recommend_retry_review(self):
        parcel = self.make_parcel()
        Parcel.objects.filter(pk=parcel.pk).update(
            status=Parcel.Status.SCHEDULED_FOR_RETRY,
            delivery_attempts=1,
            failure_reason=Parcel.FailureReason.CUSTOMER_UNAVAILABLE,
        )
        parcel.refresh_from_db()
        result = assess_parcel_delay_risk(parcel)
        self.assertEqual(result["level"], "MEDIUM")
        self.assertIn("failed delivery attempt", result["reasons"][0]["message"])

    def test_admin_dashboard_shows_risk_and_agent_dashboard_does_not(self):
        parcel = self.make_parcel(
            expected_delivery_date=timezone.localdate() - timedelta(days=1)
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Smart delivery delay risk")
        self.assertContains(response, parcel.tracking_id)

        self.client.force_login(self.agent)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Smart delivery delay risk")

    def test_customer_tracking_gets_warning_only_for_owned_parcel(self):
        overdue = self.make_parcel(
            expected_delivery_date=timezone.localdate() - timedelta(days=1)
        )
        other_customer = User.objects.create_user(
            username="risk_other_customer", password="TestPassword123!", role="CUSTOMER"
        )
        other_parcel = self.make_parcel(
            customer=other_customer,
            created_by=other_customer,
            expected_delivery_date=timezone.localdate() - timedelta(days=1),
        )
        self.client.force_login(self.customer)
        own = self.client.get(
            f"{reverse('public_parcel_track')}?tracking_id={overdue.tracking_id}"
        )
        other = self.client.get(
            f"{reverse('public_parcel_track')}?tracking_id={other_parcel.tracking_id}"
        )
        self.assertContains(own, "delay risk")
        self.assertNotContains(other, "delay risk")
