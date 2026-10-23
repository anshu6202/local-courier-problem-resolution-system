from django import forms
from django.core.validators import RegexValidator
from django.utils import timezone
from .models import Parcel


class ParcelForm(forms.ModelForm):
    class Meta:
        model = Parcel
        fields = [
            "sender_name",
            "sender_phone",
            "receiver_name",
            "receiver_phone",
            "delivery_address",
            "expected_delivery_date",
            "customer",
            "assigned_agent",
            "package_weight",
            "package_type",
        ]
        labels = {
            "sender_name": "Sender name",
            "sender_phone": "Sender phone",
            "receiver_name": "Recipient name",
            "receiver_phone": "Recipient phone",
            "customer": "Linked customer account",
        }

        widgets = {
            "expected_delivery_date": forms.DateInput(
                attrs={"type": "date"}
            ),
        }


class CustomerParcelBookingForm(forms.ModelForm):
    class Meta:
        model = Parcel
        fields = [
            "sender_name",
            "sender_phone",
            "receiver_name",
            "receiver_phone",
            "delivery_address",
            "expected_delivery_date",
        ]
        labels = {
            "receiver_name": "Recipient name",
            "receiver_phone": "Recipient phone",
        }
        widgets = {
            "expected_delivery_date": forms.DateInput(
                attrs={"type": "date"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expected_delivery_date"].widget.attrs["min"] = (
            timezone.localdate().isoformat()
        )

    def clean_expected_delivery_date(self):
        delivery_date = self.cleaned_data["expected_delivery_date"]
        if delivery_date < timezone.localdate():
            raise forms.ValidationError("Expected delivery date cannot be in the past.")
        return delivery_date


class RedeliveryRequestForm(forms.Form):
    preferred_delivery_date = forms.DateField(
        label="Preferred redelivery date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reason = forms.CharField(
        label="Reason (optional)",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_delivery_date"].widget.attrs["min"] = (
            timezone.localdate().isoformat()
        )

    def clean_preferred_delivery_date(self):
        preferred_date = self.cleaned_data["preferred_delivery_date"]
        if preferred_date < timezone.localdate():
            raise forms.ValidationError("Preferred redelivery date cannot be in the past.")
        return preferred_date


class RedeliveryDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[("APPROVED", "Approve request"), ("REJECTED", "Reject request")]
    )
    assigned_agent = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label="Assign agent (optional; keeps current assignment if blank)",
    )
    decision_note = forms.CharField(
        required=False,
        max_length=1000,
        label="Decision note",
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model

        self.fields["assigned_agent"].queryset = get_user_model().objects.filter(
            role="AGENT",
            is_active=True,
            is_active_agent=True,
        ).order_by("username")

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("decision") == "REJECTED"
            and not cleaned_data.get("decision_note", "").strip()
        ):
            self.add_error("decision_note", "Add a brief reason for rejecting this request.")
        return cleaned_data



class ParcelStatusUpdateForm(forms.Form):
    status = forms.ChoiceField(
        choices=[],
        label="Update Parcel Status",
    )
    note = forms.CharField(
        required=False,
        max_length=255,
        label="Delivery note (optional)",
        widget=forms.TextInput(attrs={"placeholder": "Add a short delivery update"}),
    )
    delivered_to = forms.CharField(
        required=False,
        max_length=100,
        label="Received by",
        widget=forms.TextInput(attrs={"placeholder": "Recipient or authorized receiver"}),
    )
    failure_reason = forms.ChoiceField(
        choices=[("", "Choose a reason"), *Parcel.FailureReason.choices],
        required=False,
        label="Reason for failed delivery",
    )
    otp = forms.CharField(
        required=False,
        min_length=4,
        max_length=4,
        validators=[RegexValidator(r"^\d{4}$", "Enter the 4-digit numeric delivery code.")],
        label="Customer delivery OTP",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[0-9]{4}", "autocomplete": "one-time-code"}),
    )

    def __init__(self, *args, current_status, **kwargs):
        super().__init__(*args, **kwargs)

        if current_status == "REGISTERED":
            self.fields["status"].choices = [
                ("IN_TRANSIT", "In Transit"),
            ]

        elif current_status in {"IN_TRANSIT", "SCHEDULED_FOR_RETRY"}:
            if current_status == "SCHEDULED_FOR_RETRY":
                self.fields["status"].choices = [("IN_TRANSIT", "Start delivery retry")]
                return
            self.fields["status"].choices = [
                ("DELIVERED", "Delivered"),
                ("FAILED", "Delivery Failed"),
            ]
            if self.data.get("status") == "DELIVERED":
                self.fields["delivered_to"].required = True
                self.fields["otp"].required = True
                self.fields["otp"].widget.attrs["required"] = True
            if self.data.get("status") == "FAILED":
                self.fields["failure_reason"].required = True
