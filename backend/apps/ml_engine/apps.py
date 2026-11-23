from django.apps import AppConfig


class MlEngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ml_engine"

    def ready(self):
        # Importing registers the @receiver handlers in signals.py.
        # Guard against double-registration in interactive reloads.
        try:
            from apps.ml_engine import signals  # noqa: F401
        except Exception:
            # Never block startup, but a missing signal handler (e.g. the MRM
            # dossier refresh) must be visible rather than silently absent.
            import logging

            logging.getLogger(__name__).exception("ml_engine signal handlers failed to register")
