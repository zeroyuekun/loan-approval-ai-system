from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.loans.models import AuditLog

from .models import CustomUser


def _changed_fields(message):
    """Field labels from Django's admin change message (list form); never values."""
    if not isinstance(message, list):
        return []
    fields = []
    for entry in message:
        for verb in ("added", "changed"):
            fields.extend((entry.get(verb) or {}).get("fields", []))
    return fields


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = UserAdmin.fieldsets + (("Additional Info", {"fields": ("role", "phone")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Additional Info", {"fields": ("role", "phone")}),)

    # Role, superuser status and password changes grant or remove access, so
    # every admin write to a user also goes into the hash-chained AuditLog,
    # not only Django's LogEntry. Django calls these hooks for the change
    # form, the password form and the add form alike. Field names only: the
    # password hash and other values stay out of the audit trail.
    def _audit(self, request, obj, action, message):
        AuditLog.objects.create(
            user=request.user,
            action=action,
            resource_type="CustomUser",
            resource_id=str(obj.pk),
            details={"source": "django_admin", "changed": _changed_fields(message)},
            ip_address=request.META.get("REMOTE_ADDR"),
        )

    def log_addition(self, request, obj, message):
        self._audit(request, obj, "user_added", message)
        return super().log_addition(request, obj, message)

    def log_change(self, request, obj, message):
        self._audit(request, obj, "user_changed", message)
        return super().log_change(request, obj, message)

    def log_deletions(self, request, queryset):
        for obj in queryset:
            self._audit(request, obj, "user_deleted", [])
        return super().log_deletions(request, queryset)
