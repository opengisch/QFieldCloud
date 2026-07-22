from django.test import SimpleTestCase

from qfieldcloud.project.utils.geometry_utils import transform_wkt_crs


class QfcTestCase(SimpleTestCase):
    def test_transform_wkt_crs_valid(self):
        """A WKT point in a real CRS transforms into WGS84 degrees.

        EPSG:3857 (Web Mercator)'s origin (0, 0) is, by definition, exactly
        (0, 0) in WGS84 (equator/prime meridian), so this is an exact check.
        """
        geometry = transform_wkt_crs("POINT (0 0)", "EPSG:3857")

        self.assertAlmostEqual(geometry.x, 0.0, places=6)
        self.assertAlmostEqual(geometry.y, 0.0, places=6)

    def test_transform_wkt_crs_invalid_wkt_raises(self):
        """A malformed WKT string raises ValueError."""
        with self.assertRaises(ValueError):
            transform_wkt_crs("NOT WKT", "EPSG:3857")

    def test_transform_wkt_crs_out_of_projection_domain_raises(self):
        """Coordinates outside a projection's valid domain raise ValueError."""
        with self.assertRaises(ValueError):
            transform_wkt_crs(
                "POINT (500000 4649776)", "EPSG:4326", target_crs="EPSG:3857"
            )

    def test_transform_wkt_crs_local_crs_raises(self):
        """A local CRS with no real geodetic datum raises ValueError."""

        local_cs_wkt = (
            'LOCAL_CS["Non-Earth (Meter)",'
            'LOCAL_DATUM["Local Datum",0],'
            'UNIT["Meter",1.0],'
            'AXIS["X",EAST],AXIS["Y",NORTH]]'
        )

        with self.assertRaises(ValueError):
            transform_wkt_crs("POINT (500000 4649776)", local_cs_wkt)

    def test_transform_wkt_crs_valid_non_default_target(self):
        """A point within a non-EPSG:4326 target's area of use transforms successfully.

        Latitude 45 is well within EPSG:3857 (Web Mercator)'s area of use
        (85.06°S to 85.06°N), so this should succeed without raising.
        """
        geometry = transform_wkt_crs(
            "POINT (0 45)", "EPSG:4326", target_crs="EPSG:3857"
        )

        self.assertAlmostEqual(geometry.x, 0.0, places=6)

    def test_transform_wkt_crs_outside_non_default_target_area_of_use_raises(self):
        """A point outside a non-EPSG:4326 target's specific area of use raises.

        Latitude 89 is a valid WGS84 latitude (within the global -90/90 range),
        but EPSG:3857 (Web Mercator)'s area of use only covers 85.06°S to
        85.06°N. This proves the check validates against `target_crs`'s own
        area of use, not a hardcoded -180/180, -90/90 range.
        """
        with self.assertRaises(ValueError):
            transform_wkt_crs("POINT (0 89)", "EPSG:4326", target_crs="EPSG:3857")

    def test_transform_wkt_crs_mismatched_crs_raises(self):
        """A mislabeled CRS (source == target) is caught by the area-of-use check.

        When `source_crs` and `target_crs` are the same, no real transform happens,
        so coordinates that are actually in a different unit/CRS than declared
        would otherwise pass through as-is. The area-of-use validation against
        `target_crs` catches this: these values land far outside EPSG:4326's
        valid lat/lon range.
        """
        with self.assertRaises(ValueError):
            transform_wkt_crs(
                "POINT (500000 4649776)", "EPSG:4326", target_crs="EPSG:4326"
            )
