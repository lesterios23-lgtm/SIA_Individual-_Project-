"""App configuration for the HR Limbus integration."""

from django.apps import AppConfig


class LimbusIntegrationConfig(AppConfig):
    """Wire the HR lifecycle signals that fill the outbox."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "limbus_integration"
    verbose_name = "Limbus Integration (HR)"

    def ready(self):
        # Importing the module connects the receivers. Keep the import here so
        # the app registry is populated before model imports run.
        from . import signals  # noqa: F401
