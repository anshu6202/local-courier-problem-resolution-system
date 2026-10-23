from django.contrib.auth.forms import UserCreationForm

from .models import User


class CustomerRegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        # Public registration can only create customer accounts.
        user.role = User.Role.CUSTOMER
        if commit:
            user.save()
        return user
