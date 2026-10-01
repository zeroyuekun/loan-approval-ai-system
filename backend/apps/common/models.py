"""Shared abstract models for cross-cutting concerns."""

from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """Default queryset that excludes soft-deleted records."""

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):
        """On a model with ``SOFT_DELETE_ON_DELETE``, soft-delete every live row
        (bulk ``.delete()`` callers, including the Django admin's delete
        action, never hard delete by accident). Returns ``(count, {label:
        count})`` like Django. Other models delete normally."""
        if not getattr(self.model, "SOFT_DELETE_ON_DELETE", False):
            return super().delete()
        count = self.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
        return count, {self.model._meta.label: count}

    delete.alters_data = True
    delete.queryset_only = True

    def hard_delete(self):
        """Physically delete (with CASCADE). Retention purges only."""
        return super().delete()

    hard_delete.alters_data = True
    hard_delete.queryset_only = True


class SoftDeleteManager(models.Manager):
    """Manager that returns only non-deleted records by default.

    Use ``all_with_deleted()`` to include soft-deleted records.
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def dead(self):
        return SoftDeleteQuerySet(self.model, using=self._db).dead()


class SoftDeleteModel(models.Model):
    """Abstract base providing soft-delete via a ``deleted_at`` timestamp.

    ``soft_delete()`` marks a record deleted and ``restore()`` undoes it.
    A model that sets ``SOFT_DELETE_ON_DELETE = True`` also soft-deletes on
    ``delete()`` (instance and queryset), so no API, admin or bulk caller can
    hard delete it by accident; ``hard_delete()`` physically removes the row
    and its CASCADE children, and only the retention purge calls it.

    The default manager filters out deleted records. Use
    ``Model.all_objects.all_with_deleted()`` to query everything.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    SOFT_DELETE_ON_DELETE = False

    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager()  # aliased; use all_with_deleted() explicitly

    class Meta:
        abstract = True

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def delete(self, using=None, keep_parents=False):
        if not self.SOFT_DELETE_ON_DELETE:
            return super().delete(using=using, keep_parents=keep_parents)
        self.soft_delete()
        return 1, {self._meta.label: 1}

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])

    @property
    def is_deleted(self):
        return self.deleted_at is not None
