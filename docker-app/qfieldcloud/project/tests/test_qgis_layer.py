import logging

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import TestCase

from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.filestorage.models import File, FileVersion
from qfieldcloud.project.enums import (
    QgsFieldConstraintStrength,
    QgsGeometryType,
    QgsLayerType,
    QtType,
)
from qfieldcloud.project.models import (
    Project,
    QgisLayer,
    QgisLayerField,
    QgisProject,
)

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    """Tests for `QgisLayer` and `QgisLayerField` models."""

    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.qgis_project = self._create_qgis_project()

    def _create_qgis_project(self) -> QgisProject:
        """Create a `Project`, an uploaded `.qgs` file and its `QgisProject`, so a `QgisLayer` has something to attach to."""
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
        """Test very long qgis layer ids.

        A `qgis_layer_id` long enough to overflow the Postgres btree index
        row size limit used to break the unique constraint. The constraint now
        indexes `MD5(qgis_layer_id)` instead, which is fixed-size, so it no longer does.
        """
        long_id = "x" * 5000

        layer = self._create_layer(long_id)

        self.assertEqual(layer.qgis_layer_id, long_id)

    def test_duplicate_qgis_layer_id_in_same_project_violates_constraint(self):
        """Test two layers with the same layer id.

        Two layers with the same `qgis_layer_id` in the same project still
        violate the uniqueness constraint, now enforced on the hash.
        """
        self._create_layer("layer1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_layer("layer1", name="layer1 duplicate")

    def test_empty_qgis_layer_id_hashes_like_any_other_string(self):
        """Test an empty layer id.

        An empty `qgis_layer_id` hashes like any other value. A second
        layer with the same empty `qgis_layer_id` in the same project still
        violates the constraint.
        """
        self._create_layer("", name="group", crs="", geom_type=QgsGeometryType.Null)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_layer(
                "", name="group2", crs="", geom_type=QgsGeometryType.Null
            )

    def test_update_from_details_create_update_delete_cycle(self):
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

    def test_missing_primary_key_warning_skipped_for_readonly_layer(self):
        project = self.qgis_project.project
        project.the_qgis_file = self.qgis_project.file_version.file
        project.save(update_fields=["the_qgis_file"])

        with self.subTest(
            "Test problems skips the primary key warning for a read-only layer"
        ):
            self._create_layer(
                "readonly_layer",
                is_readonly=True,
                qfs_settings={"qfc_source_data_pk_name": ""},
            )

            self.assertEqual(project.problems, [])

        with self.subTest(
            "Test problems warns about the missing primary key of an editable layer"
        ):
            self._create_layer(
                "editable_layer",
                ordering=1,
                qfs_settings={"qfc_source_data_pk_name": ""},
            )

            self.assertEqual(
                project.problems,
                [
                    {
                        "layer": "editable_layer",
                        "level": "warning",
                        "code": "layer_problem",
                        "description": 'Layer "editable_layer" does not support the `primary key` attribute. The layer will be read-only on QField.',
                        "solution": "To make the layer editable on QField, store the layer data in a GeoPackage or PostGIS layer, using a single column for the primary key.",
                    }
                ],
            )

    def test_layer_sync_also_syncs_the_layer_fields(self):
        with self.subTest("Test the layer sync creates the fields in order"):
            QgisLayer.objects.update_from_details(
                self.qgis_project,
                ["layer1"],
                {
                    "layer1": self._layer_details(
                        fields=[
                            {"name": "id", "type": QtType.Int},
                            {"name": "label", "type": QtType.QString},
                        ]
                    ),
                },
            )

            layer = self.qgis_project.layers.get(qgis_layer_id="layer1")

            self.assertEqual(
                list(layer.fields.values_list("name", "ordering", "type")),
                [("id", 0, QtType.Int), ("label", 1, QtType.QString)],
            )

        with self.subTest(
            "Test the layer sync removes the fields when the details have none"
        ):
            QgisLayer.objects.update_from_details(
                self.qgis_project,
                ["layer1"],
                {"layer1": self._layer_details(fields=None)},
            )

            self.assertEqual(list(layer.fields.values_list("name", flat=True)), [])

    def test_very_long_field_name_does_not_break_unique_constraint(self):
        """Test very long field names.

        A field `name` long enough to overflow the Postgres btree index row size limit.
        """
        layer = self._create_layer("layer1")
        long_name = "x" * 10000

        QgisLayerField.objects.update_from_details(layer, [{"name": long_name}])

        self.assertEqual(layer.fields.get().name, long_name)

    def test_duplicate_field_name_in_same_layer_violates_constraint(self):
        layer = self._create_layer("layer1")
        QgisLayerField.objects.create(layer=layer, name="field1", ordering=0)

        with self.assertRaises(IntegrityError), transaction.atomic():
            QgisLayerField.objects.create(layer=layer, name="field1", ordering=1)

    def test_field_sync_falls_back_on_missing_or_invalid_values(self):
        """Test malformed field details from the worker.

        If `after_docker_run` raises, the job fails and the project's `QgisProject` is deleted,
        so no single unexpected value may break the save.
        """
        layer = self._create_layer("layer1")

        QgisLayerField.objects.update_from_details(
            layer,
            [
                {"name": "only_name"},
                {
                    "name": "explicit_nulls",
                    "alias": None,
                    "comment": None,
                    "type": None,
                    "type_display": None,
                    "length": None,
                    "precision": None,
                    "constraint_strength": None,
                    "constraint_expression": None,
                    "constraint_expression_description": None,
                    "constraint_expression_strength": None,
                    "is_unique_strength": None,
                    "default_value": None,
                    "set_default_value_on_update": None,
                    "widget_type": None,
                    "widget_config": None,
                },
                {"name": "type_name_string", "type": "String"},
                {"name": "unknown_type", "type": 0},
                {"name": "unknown_strength", "constraint_strength": "very_hard"},
                {"name": "", "alias": "skipped"},
                {
                    "name": "long_values",
                    "type_display": "t" * 500,
                    "widget_type": "w" * 500,
                },
            ],
        )

        with self.subTest("Test a field with only a name gets the default values"):
            field = layer.fields.get(name="only_name")
            self.assertEqual(field.alias, "")
            self.assertEqual(field.comment, "")
            self.assertIsNone(field.type)
            self.assertEqual(field.type_display, "")
            self.assertEqual(field.length, 0)
            self.assertEqual(field.precision, 0)
            self.assertEqual(
                field.is_not_null_strength, QgsFieldConstraintStrength.NOT_SET
            )
            self.assertEqual(field.constraint_expression, "")
            self.assertEqual(field.constraint_expression_description, "")
            self.assertEqual(
                field.constraint_expression_strength,
                QgsFieldConstraintStrength.NOT_SET,
            )
            self.assertEqual(
                field.is_unique_strength, QgsFieldConstraintStrength.NOT_SET
            )
            self.assertEqual(field.default_value, "")
            self.assertFalse(field.set_default_value_on_update)
            self.assertEqual(field.widget_type, "")
            self.assertEqual(field.widget_config, {})

        with self.subTest("Test explicit null values fall back to the default values"):
            field = layer.fields.get(name="explicit_nulls")
            self.assertEqual(field.alias, "")
            self.assertIsNone(field.type)
            self.assertEqual(field.length, 0)
            self.assertEqual(
                field.is_not_null_strength, QgsFieldConstraintStrength.NOT_SET
            )
            self.assertFalse(field.set_default_value_on_update)
            self.assertEqual(field.widget_config, {})

        with self.subTest("Test a non-integer type is saved as null"):
            self.assertIsNone(layer.fields.get(name="type_name_string").type)

        with self.subTest("Test type 0 is saved as `UnknownType`, not null"):
            self.assertEqual(
                layer.fields.get(name="unknown_type").type, QtType.UnknownType
            )

        with self.subTest("Test an unknown constraint strength is saved as not set"):
            self.assertEqual(
                layer.fields.get(name="unknown_strength").is_not_null_strength,
                QgsFieldConstraintStrength.NOT_SET,
            )

        with self.subTest("Test the sync skips a field without a name"):
            self.assertEqual(
                list(layer.fields.values_list("name", flat=True)),
                [
                    "only_name",
                    "explicit_nulls",
                    "type_name_string",
                    "unknown_type",
                    "unknown_strength",
                    "long_values",
                ],
            )

        with self.subTest("Test long type display and widget type values save in full"):
            field = layer.fields.get(name="long_values")
            self.assertEqual(field.type_display, "t" * 500)
            self.assertEqual(field.widget_type, "w" * 500)

    def test_field_sync_create_update_delete_cycle(self):
        layer = self._create_layer("layer1")

        with self.subTest("Test the first sync creates the fields in order"):
            QgisLayerField.objects.update_from_details(
                layer,
                [
                    {"name": "field1", "alias": "Field 1"},
                    {"name": "field2"},
                ],
            )

            self.assertEqual(
                list(layer.fields.values_list("name", "ordering", "alias")),
                [("field1", 0, "Field 1"), ("field2", 1, "")],
            )

        with self.subTest(
            "Test a re-sync adds, reorders and updates fields and deletes the missing one"
        ):
            QgisLayerField.objects.update_from_details(
                layer,
                [
                    {"name": "field3"},
                    {"name": "field1", "alias": "Field 1 renamed"},
                ],
            )

            self.assertEqual(
                list(layer.fields.values_list("name", "ordering", "alias")),
                [("field3", 0, ""), ("field1", 1, "Field 1 renamed")],
            )
