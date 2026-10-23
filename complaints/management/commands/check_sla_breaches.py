from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from complaints.models import Complaint, ComplaintHistory, ComplaintNotification


def _notify_admins(complaint, notification_type, message):
    User = get_user_model()
    admins = User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(role="ADMIN"))
    for admin in admins.iterator():
        ComplaintNotification.objects.get_or_create(
            complaint=complaint,
            recipient=admin,
            notification_type=notification_type,
            defaults={"message": message},
        )


class Command(BaseCommand):
    help = "Notify admins of approaching SLAs and escalate overdue active complaints."

    def handle(self, *args, **options):
        now = timezone.now()
        approaching_hours = max(0, int(getattr(settings, "COMPLAINT_SLA_APPROACHING_HOURS", 4)))
        approaching_until = now + timedelta(hours=approaching_hours)
        approaching_ids = Complaint.objects.filter(
            status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
            is_escalated=False,
            sla_deadline__gt=now,
            sla_deadline__lte=approaching_until,
        ).values_list("pk", flat=True)
        approaching_count = 0
        for complaint in Complaint.objects.filter(pk__in=approaching_ids).select_related("parcel").iterator():
            _notify_admins(
                complaint,
                ComplaintNotification.Type.APPROACHING,
                f"Complaint for parcel {complaint.parcel.tracking_id} is approaching its SLA deadline.",
            )
            approaching_count += 1

        complaint_ids = Complaint.objects.filter(
            status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
            sla_deadline__lte=now,
            is_escalated=False,
        ).values_list("pk", flat=True)

        escalated_count = 0
        for complaint_id in complaint_ids.iterator():
            with transaction.atomic():
                complaint = Complaint.objects.select_for_update().get(pk=complaint_id)
                if (
                    complaint.status not in {Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS}
                    or complaint.is_escalated
                    or complaint.sla_deadline > now
                ):
                    continue

                complaint.is_escalated = True
                complaint.save(update_fields=["is_escalated"])
                ComplaintHistory.objects.create(
                    complaint=complaint,
                    changed_by=complaint.assigned_agent or complaint.reported_by,
                    old_status=complaint.status,
                    new_status=complaint.status,
                    note=(
                        "SLA breached at "
                        f"{timezone.localtime(complaint.sla_deadline):%Y-%m-%d %H:%M %Z}; "
                        "case auto-escalated."
                    ),
                )
                _notify_admins(
                    complaint,
                    ComplaintNotification.Type.BREACHED,
                    f"Complaint for parcel {complaint.parcel.tracking_id} has breached its SLA deadline.",
                )
                _notify_admins(
                    complaint,
                    ComplaintNotification.Type.ESCALATED,
                    f"Complaint for parcel {complaint.parcel.tracking_id} was escalated after its SLA breach.",
                )
                escalated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Checked SLA: {approaching_count} approaching complaint(s), "
            f"{escalated_count} escalated complaint(s)."
        ))
