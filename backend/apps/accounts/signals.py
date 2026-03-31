from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomerProfile, CustomUser


@receiver(post_save, sender=CustomUser)
def create_customer_profile(sender, instance, created, **kwargs):
    """Auto-create a CustomerProfile when a new user is created."""
    if created and instance.role == "customer":
        CustomerProfile.objects.get_or_create(user=instance)
