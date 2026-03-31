"""Shared abstract models for cross-cutting concerns."""

from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """Default queryset that excludes soft-deleted records."""

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


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

    Records are never physically deleted by default. Use ``soft_delete()``
    to mark a record as deleted and ``restore()`` to undo it.

    The default manager filters out deleted records. Use
    ``Model.all_objects.all_with_deleted()`` to query everything.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager()  # aliased; use all_with_deleted() explicitly

    class Meta:
        abstract = True

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])

    @property
    def is_deleted(self):
        return self.deleted_at is not None
