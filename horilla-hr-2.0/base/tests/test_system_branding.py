"""Tests for the configured visible system branding."""

from django.conf import settings
from django.test import SimpleTestCase

from base.context_processors import system_branding


class SystemBrandingTests(SimpleTestCase):
    def test_context_processor_exposes_configured_system_names(self):
        self.assertEqual(
            system_branding(None),
            {
                "system_name": "EC: Energy Cycle Human Capital",
                "system_short_name": "EC Human Capital",
            },
        )
        self.assertEqual(settings.SYSTEM_NAME, "EC: Energy Cycle Human Capital")
        self.assertEqual(settings.SYSTEM_SHORT_NAME, "EC Human Capital")
