import logging

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import TestCase

from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.filestorage.models import File, FileVersion
from qfieldcloud.project.enums import QgsGeometryType, QgsLayerType
from qfieldcloud.project.models import Project, QgisLayer, QgisProject

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    """Tests for `QgisLayer` model."""

    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.qgis_project = self._create_qgis_project()

    def _create_qgis_project(self) -> QgisProject:
        """Create a `Project`, an uploaded `.qgs` file and its `QgisProject`, so
        a `QgisLayer` has something to attach to.
        """
        project = Project.objects.create(name="project", owner=self.user1)

        file_version = FileVersion.objects.add_version(
            project=project,
            filename="project.qgs",
            content=ContentFile(b"", "project.qgs"),
            file_type=File.FileType.PROJECT_FILE,
            uploaded_by=self.user1,
        )

        return QgisProject.objects.create(
            project=project, file_version=file_version, crs="EPSG:3857"
        )

    def _create_layer(self, qgis_layer_id: str, **overrides) -> QgisLayer:
        """Create a `QgisLayer` on `self.qgis_project` with defaults.
        Pass `overrides` to change any field.
        """
        kwargs = {
            "qgis_project": self.qgis_project,
            "qgis_layer_id": qgis_layer_id,
            "name": qgis_layer_id,
            "crs": "EPSG:3857",
            "geom_type": QgsGeometryType.Point,
            "layer_type": QgsLayerType.Vector,
            "ordering": 0,
        }
        kwargs.update(overrides)
        return QgisLayer.objects.create(**kwargs)

    def _layer_details(self, **overrides) -> dict:
        """Build one layer-details dict in the shape `update_from_details`
        expects. Pass `overrides` to change any key.
        """
        details = {
            "name": "layer",
            "crs": "EPSG:3857",
            "type": QgsLayerType.Vector,
            "geom_type": QgsGeometryType.Point,
            "is_valid": True,
        }
        details.update(overrides)
        return details

    def test_very_long_qgis_layer_id_does_not_break_unique_constraint(self):
        """A `qgis_layer_id` long enough to overflow the Postgres btree index
        row size limit used to break the unique constraint. The constraint now
        indexes `MD5(qgis_layer_id)` instead, which is fixed-size, so it no longer does.
        """
        long_id = "x" * 5000

        layer = self._create_layer(long_id)

        self.assertEqual(layer.qgis_layer_id, long_id)

    def test_duplicate_qgis_layer_id_in_same_project_violates_constraint(self):
        """Two layers with the same `qgis_layer_id` in the same project still
        violate the uniqueness constraint, now enforced on the hash.
        """
        self._create_layer("layer1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_layer("layer1", name="layer1 duplicate")

    def test_empty_qgis_layer_id_hashes_like_any_other_string(self):
        """An empty `qgis_layer_id` hashes like any other value. A second
        layer with the same empty `qgis_layer_id` in the same project still
        violates the constraint.
        """
        self._create_layer("", name="group", crs="", geom_type=QgsGeometryType.Null)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_layer(
                "", name="group2", crs="", geom_type=QgsGeometryType.Null
            )

    def test_update_from_details_create_update_delete_cycle(self):
        """`update_from_details` creates, renames, adds and drops `QgisLayer`
        rows correctly.
        """
        QgisLayer.objects.update_from_details(
            self.qgis_project,
            ["layer1", "layer2"],
            {
                "layer1": self._layer_details(name="layer1"),
                "layer2": self._layer_details(name="layer2"),
            },
        )

        self.assertTrue(
            self.qgis_project.layers.filter(qgis_layer_id="layer1").exists()
        )
        self.assertTrue(
            self.qgis_project.layers.filter(qgis_layer_id="layer2").exists()
        )

        # Re-sync: `layer2` is dropped, `layer3` is added, `layer1` is renamed.
        QgisLayer.objects.update_from_details(
            self.qgis_project,
            ["layer1", "layer3"],
            {
                "layer1": self._layer_details(name="layer1 renamed"),
                "layer3": self._layer_details(name="layer3"),
            },
        )

        self.assertFalse(
            self.qgis_project.layers.filter(qgis_layer_id="layer2").exists()
        )

        layer1 = self.qgis_project.layers.get(qgis_layer_id="layer1")
        self.assertEqual(layer1.name, "layer1 renamed")

        self.assertTrue(
            self.qgis_project.layers.filter(qgis_layer_id="layer3").exists()
        )
