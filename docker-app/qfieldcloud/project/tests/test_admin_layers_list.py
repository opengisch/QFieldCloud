import logging

from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.filestorage.models import File, FileVersion
from qfieldcloud.project.admin import qgis_project_layers_list
from qfieldcloud.project.enums import LayerErrorCode, QgsGeometryType, QgsLayerType
from qfieldcloud.project.models import Project, QgisLayer, QgisProject

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        project = Project.objects.create(name="project", owner=self.user1)
        file_version = FileVersion.objects.add_version(
            project=project,
            filename="project.qgs",
            content=ContentFile(b"", "project.qgs"),
            file_type=File.FileType.PROJECT_FILE,
            uploaded_by=self.user1,
        )
        self.qgis_project = QgisProject.objects.create(
            project=project, file_version=file_version, crs="EPSG:3857"
        )

    def test_qgis_project_layers_list_renders_a_dash_without_layers(self):
        self.assertEqual(qgis_project_layers_list(self.qgis_project), "-")

    def test_qgis_project_layers_list_renders_an_unfold_table_of_layers(self):
        layer = QgisLayer.objects.create(
            qgis_project=self.qgis_project,
            qgis_layer_id="points",
            name="points",
            crs="EPSG:3857",
            geom_type=QgsGeometryType.Point,
            layer_type=QgsLayerType.Vector,
            ordering=0,
            is_valid=False,
            error_code=LayerErrorCode.INVALID_LAYER,
        )

        soup = BeautifulSoup(qgis_project_layers_list(self.qgis_project), "html.parser")

        with self.subTest("Test the table has a header per column"):
            self.assertEqual(
                [header.get_text(strip=True) for header in soup.select("thead th")],
                ["Name", "Type", "Geometry", "Valid", "Error"],
            )

        with self.subTest("Test the row shows the layer details"):
            self.assertEqual(
                [cell.get_text(strip=True) for cell in soup.select("tbody td")],
                ["points", "Vector", "Point", "", "Invalid layer"],
            )

        with self.subTest("Test the layer name links to the layer's admin page"):
            self.assertEqual(
                soup.select_one("tbody td a")["href"],
                reverse("admin:project_qgislayer_change", args=[layer.pk]),
            )

        with self.subTest("Test the valid column shows the boolean icon"):
            self.assertEqual(
                soup.select("tbody td")[3].select_one("img")["alt"], "False"
            )
