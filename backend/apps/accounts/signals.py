import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomerProfile, CustomUser

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CustomUser)
def create_customer_profile(sender, instance, created, **kwargs):
    """Auto-create a CustomerProfile when a new user is created."""
    if created and instance.role == "customer":
        try:
            CustomerProfile.objects.get_or_create(user=instance)
        except Exception:
            logger.exception(
                "Failed to auto-create CustomerProfile for user %s",
                instance.pk,
            )
