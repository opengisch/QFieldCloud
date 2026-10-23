import logging

from django.test import SimpleTestCase
from unfold.admin import ModelAdmin

from qfieldcloud.core.admin import qfc_admin_site

logging.disable(logging.CRITICAL)


class QfcTestCase(SimpleTestCase):
    def test_all_registered_admins_are_unfold_admins(self):
        """Every admin must be based on Unfold's `ModelAdmin`, otherwise its forms and changelist miss Unfold's widgets.

        The constance `Config` admin is the only exception: `unfold.contrib.constance` styles it through templates.
        """
        non_unfold_admins = []

        for model, model_admin in qfc_admin_site._registry.items():
            if isinstance(model_admin, ModelAdmin):
                continue

            non_unfold_admins.append(model._meta.label)

        self.assertEqual(non_unfold_admins, ["constance.Config"])
