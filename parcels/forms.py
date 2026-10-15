from django import forms
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
        ]

        widgets = {
            "expected_delivery_date": forms.DateInput(
                attrs={"type": "date"}
            ),
        }



class ParcelStatusUpdateForm(forms.Form):
    status = forms.ChoiceField(
        choices=[],
        label="Update Parcel Status",
    )

    def __init__(self, *args, current_status, **kwargs):
        super().__init__(*args, **kwargs)

        if current_status == "REGISTERED":
            self.fields["status"].choices = [
                ("IN_TRANSIT", "In Transit"),
            ]

        elif current_status == "IN_TRANSIT":
            self.fields["status"].choices = [
                ("DELIVERED", "Delivered"),
                ("FAILED", "Delivery Failed"),
            ]
