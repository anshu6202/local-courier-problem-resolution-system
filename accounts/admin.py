from django.contrib import admin

# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Courier Profile", {"fields": ("role", "phone_number", "branch_code", "is_active_agent")}),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Courier Profile", {"fields": ("role", "phone_number", "branch_code", "is_active_agent")}),
    )

    list_display = (
        "username",
        "email",
        "role",
        "phone_number",
        "branch_code",
        "is_active_agent",
        "is_staff",
    )
