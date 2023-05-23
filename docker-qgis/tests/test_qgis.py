import os
import shutil
import subprocess
import tempfile
import unittest


class QfcTestCase(unittest.TestCase):
    def test_package(self):
        project_directory = self.data_directory_path("simple_project")
        output_directory = tempfile.mkdtemp()

        command = [
            "docker-compose",
            "run",
            "--rm",
            "-v",
            f"{project_directory}:/io/project/",
            "-v",
            f"{output_directory}:/io/output/",
            "qgis",
            "bash",
            "-c",
            "./entrypoint.sh package /io/project/project.qgs /io/output",
        ]

        subprocess.check_call(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL
        )

        files = os.listdir(output_directory)

        self.assertIn("project_qfield.qgs", files)
        self.assertIn("france_parts_shape.shp", files)
        self.assertIn("france_parts_shape.dbf", files)
        self.assertIn("curved_polys.gpkg", files)
        self.assertIn("spatialite.db", files)

        shutil.rmtree(output_directory)

    def data_directory_path(self, path):
        basepath = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(basepath, "testdata", path)
