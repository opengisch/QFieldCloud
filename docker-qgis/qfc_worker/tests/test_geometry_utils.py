import unittest

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsRectangle

from qfc_worker.utils import reproject_extent, start_app, stop_app


class ReprojectExtentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    @classmethod
    def tearDownClass(cls):
        stop_app()

    def test_reproject_extent_valid(self):
        """
        A box in a real CRS transforms into WGS84 degrees.

        EPSG:3857 (Web Mercator)'s origin (0, 0) is, by definition, exactly
        (0, 0) in WGS84 (equator/prime meridian), so this is an exact check
        on the box's minimum corner.
        """
        extent = reproject_extent(
            QgsRectangle(0, 0, 1, 1), QgsCoordinateReferenceSystem("EPSG:3857")
        )

        self.assertAlmostEqual(extent.xMinimum(), 0.0, places=6)
        self.assertAlmostEqual(extent.yMinimum(), 0.0, places=6)

    def test_reproject_extent_invalid_parameters(self):
        """An invalid extent, source CRS, or target CRS raises ValueError."""
        valid_extent = QgsRectangle(0, 0, 1, 1)
        invalid_extent = QgsRectangle()
        valid_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        invalid_crs = QgsCoordinateReferenceSystem("")

        with self.subTest("null (unset) extent"), self.assertRaises(ValueError):
            reproject_extent(invalid_extent, valid_crs, valid_crs)

        with self.subTest("invalid source CRS"), self.assertRaises(ValueError):
            reproject_extent(valid_extent, invalid_crs, valid_crs)

        with self.subTest("invalid target CRS"), self.assertRaises(ValueError):
            reproject_extent(valid_extent, valid_crs, invalid_crs)

        with self.subTest("both invalid CRS"), self.assertRaises(ValueError):
            reproject_extent(valid_extent, invalid_crs, invalid_crs)

        if Qgis.versionInt() >= 40000:
            with self.subTest("point rectangle"), self.assertRaises(ValueError):
                reproject_extent(QgsRectangle(0, 0, 0, 0), valid_crs, valid_crs)

            with self.subTest("negative rectangle"), self.assertRaises(ValueError):
                # `normalize=False` keeps min > max as given, instead of QGIS
                # silently swapping the corners to produce a valid rectangle.
                reproject_extent(QgsRectangle(1, 1, 0, 0, False), valid_crs, valid_crs)

    def test_reproject_extent_out_of_projection_domain_raises(self):
        """Coordinates outside a projection's valid domain raise ValueError."""
        with self.assertRaises(ValueError):
            reproject_extent(
                QgsRectangle(500000, 4649776, 500001, 4649777),
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsCoordinateReferenceSystem("EPSG:3857"),
            )

    def test_reproject_extent_local_crs_raises(self):
        """A local CRS with no real geodetic datum raises ValueError."""
        local_crs_wkt = (
            'LOCAL_CS["Non-Earth (Meter)",'
            'LOCAL_DATUM["Local Datum",0],'
            'UNIT["Meter",1.0],'
            'AXIS["X",EAST],AXIS["Y",NORTH]]'
        )
        local_crs = QgsCoordinateReferenceSystem.fromWkt(local_crs_wkt)

        with self.assertRaises(ValueError):
            reproject_extent(QgsRectangle(500000, 4649776, 500001, 4649777), local_crs)

    def test_reproject_extent_valid_non_default_target(self):
        """
        A box within a non-EPSG:4326 target's area of use transforms successfully.

        Latitude 45 is well within EPSG:3857 (Web Mercator)'s area of use
        (85.06°S to 85.06°N), so this should succeed without raising.
        """
        extent = reproject_extent(
            QgsRectangle(0, 45, 1, 46),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsCoordinateReferenceSystem("EPSG:3857"),
        )

        self.assertAlmostEqual(extent.xMinimum(), 0.0, places=6)

    def test_reproject_extent_outside_non_default_target_area_of_use_raises(self):
        """
        A box outside a non-EPSG:4326 target's specific area of use raises.

        Latitude 89 is a valid WGS84 latitude (within the global -90/90 range),
        but EPSG:3857 (Web Mercator)'s area of use only covers 85.06°S to
        85.06°N. This proves the check validates against `target_crs`'s own
        area of use, not a hardcoded -180/180, -90/90 range.
        """
        with self.assertRaises(ValueError):
            reproject_extent(
                QgsRectangle(0, 89, 1, 89.5),
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsCoordinateReferenceSystem("EPSG:3857"),
            )

    def test_reproject_extent_mismatched_crs_raises(self):
        """
        A mislabeled CRS (source == target) is caught by the area-of-use check.

        When `source_crs` and `target_crs` are the same, no real transform happens,
        so coordinates that are actually in a different unit/CRS than declared
        would otherwise pass through as-is. The area-of-use validation against
        `target_crs` catches this: these values land far outside EPSG:4326's
        valid lat/lon range.
        """
        wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")

        with self.assertRaises(ValueError):
            reproject_extent(
                QgsRectangle(500000, 4649776, 500001, 4649777),
                wgs84_crs,
                wgs84_crs,
            )


if __name__ == "__main__":
    unittest.main()
