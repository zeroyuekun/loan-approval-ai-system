from django.contrib import admin


class ViewOnlyModelAdmin(admin.ModelAdmin):
    """Admin that lists and shows records but cannot add, change or delete them.

    For records that are evidence of what the pipeline did: they change only
    through the pipeline or an audited workflow, never by hand in the admin.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
