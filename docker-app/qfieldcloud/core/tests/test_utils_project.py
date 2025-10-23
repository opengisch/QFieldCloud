# from unittest import TestCase
import logging

from django.test import TestCase

from qfieldcloud.core.utils2.project import (
    is_virtual_layer_with_embedded_layers,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def test_is_virtual_layer_without_query_question_mark(self):
        source = (
            "layer=ogr:%2Fhome%2Fuser%2Ftestdata.gpkg%7Clayername%3Dpoints_xy:points_xy:&"
            "query=SELECT%20*%20FROM%20points"
        )

        self.assertFalse(is_virtual_layer_with_embedded_layers(source))

    def test_is_virtual_layer_without_embedded_layers(self):
        source = "?query=SELECT%20*%20FROM%20points"

        self.assertFalse(is_virtual_layer_with_embedded_layers(source))

    def test_is_virtual_layer_with_embedded_layers(self):
        source_with_embedded_layers = (
            "?layer=ogr:%2Fhome%2Fuser%2Ftestdata.gpkg%7Clayername%3Dpoints_xy:points_xy:&"
            "query=SELECT%20*%20FROM%20points"
        )

        self.assertTrue(
            is_virtual_layer_with_embedded_layers(source_with_embedded_layers)
        )

    def test_is_virtual_layer_with_many_embedded_layers(self):
        source_with_embedded_layers = (
            "?layer=ogr:%2Fhome%2Fuser%2Ftestdata.gpkg%7Clayername%3Dpoints_xy:points_xy:&"
            "layer=ogr:%2Fhome%2Fuser%2Ftestdata.gpkg%7Clayername%3Dpoints_xy:points_xy:&"
            "query=SELECT%20*%20FROM%20points"
        )

        self.assertTrue(
            is_virtual_layer_with_embedded_layers(source_with_embedded_layers)
        )
