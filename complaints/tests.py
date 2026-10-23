from django.test import TestCase

# Create your tests here.

from datetime import date, timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from parcels.models import Parcel
from .models import Complaint, ComplaintNotification, ComplaintUpdate

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


class ComplaintSLATests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="sla_admin", password="TestPassword123!", role="ADMIN"
        )
        self.customer = User.objects.create_user(
            username="sla_customer", password="TestPassword123!", role="CUSTOMER"
        )
        self.other_customer = User.objects.create_user(
            username="sla_other_customer", password="TestPassword123!", role="CUSTOMER"
        )
        self.parcel = Parcel.objects.create(
            sender_name="Sender", sender_phone="9876543210",
            receiver_name="Receiver", receiver_phone="9876501234",
            delivery_address="Private address",
            expected_delivery_date=date(2026, 11, 1),
            created_by=self.customer, customer=self.customer,
        )

    def make_complaint(self, *, deadline=None, status=Complaint.Status.OPEN):
        complaint = Complaint.objects.create(
            parcel=self.parcel,
            reported_by=self.customer,
            customer=self.customer,
            category=Complaint.Category.OTHER,
            description="Test complaint",
            sla_deadline=deadline or timezone.now() + timedelta(hours=24),
            status=status,
        )
        if deadline is not None:
            Complaint.objects.filter(pk=complaint.pk).update(sla_deadline=deadline)
            complaint.sla_deadline = deadline
        return complaint

    @override_settings(COMPLAINT_SLA_APPROACHING_HOURS=4)
    def test_command_creates_approaching_and_breach_alerts_once(self):
        approaching = self.make_complaint(deadline=timezone.now() + timedelta(hours=2))
        overdue = Complaint.objects.create(
            parcel=Parcel.objects.create(
                sender_name="S2", sender_phone="9876543210", receiver_name="R2",
                receiver_phone="9876501234", delivery_address="Address",
                expected_delivery_date=date(2026, 11, 1), created_by=self.customer,
                customer=self.customer,
            ),
            reported_by=self.customer, customer=self.customer,
            category=Complaint.Category.OTHER, description="Overdue",
            sla_deadline=timezone.now() - timedelta(seconds=1),
        )
        Complaint.objects.filter(pk=overdue.pk).update(
            sla_deadline=timezone.now() - timedelta(seconds=1)
        )
        call_command("check_sla_breaches", stdout=__import__("io").StringIO())
        call_command("check_sla_breaches", stdout=__import__("io").StringIO())

        self.assertEqual(ComplaintNotification.objects.filter(complaint=approaching).count(), 1)
        overdue.refresh_from_db()
        self.assertTrue(overdue.is_escalated)
        self.assertEqual(
            set(ComplaintNotification.objects.filter(complaint=overdue).values_list(
                "notification_type", flat=True
            )),
            {ComplaintNotification.Type.BREACHED, ComplaintNotification.Type.ESCALATED},
        )

    def test_resolved_complaint_is_not_escalated_or_notified(self):
        complaint = self.make_complaint(deadline=timezone.now() - timedelta(days=1))
        complaint.transition_to(Complaint.Status.RESOLVED, changed_by=self.customer)
        call_command("check_sla_breaches", stdout=__import__("io").StringIO())
        complaint.refresh_from_db()
        self.assertFalse(complaint.is_escalated)
        self.assertFalse(complaint.notifications.exists())

    def test_customer_sees_only_own_complaints_and_public_updates(self):
        own = self.make_complaint()
        other_parcel = Parcel.objects.create(
            sender_name="S3", sender_phone="9876543210", receiver_name="R3",
            receiver_phone="9876501234", delivery_address="Other address",
            expected_delivery_date=date(2026, 11, 1), created_by=self.other_customer,
            customer=self.other_customer,
        )
        other = Complaint.objects.create(
            parcel=other_parcel, reported_by=self.other_customer,
            customer=self.other_customer, category=Complaint.Category.OTHER,
            description="Other customer's issue",
        )
        ComplaintUpdate.objects.create(
            complaint=own, author=self.admin, message="Customer-visible update"
        )
        ComplaintUpdate.objects.create(
            complaint=own, author=self.admin, message="Internal discussion", is_internal=True
        )
        self.client.force_login(self.customer)
        response = self.client.get(reverse("customer_complaints"))
        self.assertContains(response, "Customer-visible update")
        self.assertNotContains(response, "Internal discussion")
        self.assertNotContains(response, "Other customer's issue")
        self.assertEqual(response.context["complaints"].get().pk, own.pk)
        self.assertNotEqual(own.pk, other.pk)

    def test_admin_notification_access_and_read_status_are_role_protected(self):
        complaint = self.make_complaint()
        notification = ComplaintNotification.objects.create(
            complaint=complaint, recipient=self.admin,
            notification_type=ComplaintNotification.Type.APPROACHING,
            message="Deadline approaching",
        )
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("admin_complaint_notifications")).status_code, 403)
        self.client.post(reverse("mark_complaint_notification_read", args=[notification.pk]))
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin_complaint_notifications")).status_code, 200)
        self.client.post(reverse("mark_complaint_notification_read", args=[notification.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_admin_dashboard_exposes_sla_counts_and_notifications(self):
        self.make_complaint(deadline=timezone.now() + timedelta(hours=1))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_complaints"], 1)
        self.assertEqual(response.context["approaching_complaint_count"], 1)
        self.assertEqual(response.context["unread_complaint_notifications"], 0)
