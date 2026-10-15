from django import forms
from .models import Complaint


class ComplaintForm(forms.ModelForm):
    tracking_id = forms.CharField(
        max_length=20,
        label="Parcel Tracking ID",
    )

    class Meta:
        model = Complaint
        fields = ["category", "description"]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Describe your parcel problem...",
                }
            ),
        }
