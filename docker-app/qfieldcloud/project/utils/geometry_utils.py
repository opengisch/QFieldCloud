from django.contrib.gis.gdal import CoordTransform, GDALException, SpatialReference
from django.contrib.gis.gdal.error import SRSException
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.geos.error import GEOSException
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError


def transform_wkt_crs(
    wkt: str, source_crs: str, target_crs: str = "EPSG:4326"
) -> GEOSGeometry:
    """Parse `wkt` as `source_crs` and transform it to `target_crs`.

    Returns:
        The transformed geometry.

    Raises:
        ValueError: if the transform itself fails, if `target_crs`'s area of
            use cannot be determined, or if the result falls outside
            `target_crs`'s declared area of use.
    """
    try:
        source_crs_obj = SpatialReference(source_crs)
        trans = CoordTransform(source_crs_obj, SpatialReference(target_crs))

        geometry = GEOSGeometry(wkt, srid=source_crs_obj.srid)
        geometry.transform(trans)
    except (ValueError, TypeError, GDALException, SRSException, GEOSException) as err:
        raise ValueError(
            f"Failed to transform {wkt=} from {source_crs=} to {target_crs=} with error ({type(err).__name__}: {err})"
        ) from err

    try:
        # GDAL's `SpatialReference` is used for the transformation, but it does not
        # expose the CRS area of use, so parse the CRS again with pyproj.
        target_crs_obj = CRS.from_user_input(target_crs)
        area = target_crs_obj.area_of_use
    except CRSError as err:
        raise ValueError(
            f"Could not determine area of use for {target_crs=} with error ({type(err).__name__}: {err})"
        ) from err

    if area is None:
        # Some CRSs (for example custom or engineering CRSs) do not define area of use.
        return geometry

    # Validate that the transformed geometry lies within the target CRS's area
    # of use. This also catches incorrectly labelled input (for example,
    # coordinates in metres declared as EPSG:4326), since no transformation is
    # performed when `source_crs == target_crs`.
    # `area_of_use` is expressed as geographic longitude/latitude bounds in
    # degrees, not in the projected units of `target_crs`, so convert those
    # bounds into `target_crs` before comparing with `geometry.extent`.
    transformer = Transformer.from_crs(
        target_crs_obj.geodetic_crs,
        target_crs_obj,
        always_xy=True,
    )
    min_x, min_y, max_x, max_y = transformer.transform_bounds(
        area.west, area.south, area.east, area.north
    )

    geom_min_x, geom_min_y, geom_max_x, geom_max_y = geometry.extent
    if not (
        min_x <= geom_min_x <= geom_max_x <= max_x
        and min_y <= geom_min_y <= geom_max_y <= max_y
    ):
        raise ValueError(
            f"Transformed geometry {wkt=} from {source_crs=} to {target_crs=} "
            f"is outside {target_crs}'s area of use: extent={geometry.extent}, "
            f"expected within=({min_x}, {min_y}, {max_x}, {max_y})"
        )

    return geometry
