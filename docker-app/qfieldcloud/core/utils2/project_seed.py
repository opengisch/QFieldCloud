from typing import TypedDict

from django.contrib.gis.geos import Polygon
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext as _

from qfieldcloud.core.models import BasemapProvider, BasemapStyle

OSM_URL = "https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png"

DEFAULT_PROJECT_EXTENT = (-180, -90, 180, 90)


class BasemapConfig(TypedDict):
    url: str
    style: str
    name: str


def parse_extent_coords(extent_coords: str) -> tuple[float, float, float, float]:
    """Parses the extent coordinates from a string and validates them for EPSG:4326.

    Args:
        extent_coords: the extent coordinates to parse in the format "minX, minY, maxX, maxY"

    Returns:
        the extent coordinates as a tuple of floats
    """
    # Expect format: "minX, minY, maxX, maxY"
    coords: list[float] = []

    try:
        for x in extent_coords.split(","):
            coords.append(float(x.strip()))
    except (ValueError, TypeError):
        raise ValidationError(
            _("Invalid extent format. Expected: minX, minY, maxX, maxY")
        )

    if len(coords) != 4:
        raise ValidationError(_("Extent must have 4 coordinates"))

    minx, miny, maxx, maxy = coords

    # Validate bounds for EPSG:4326 [https://epsg.io/4326] (WGS 84 valid range)
    max_x_extent = 180  # Valid X (longitude) range
    max_y_extent = 90  # Valid Y (latitude) range

    if not (
        -max_x_extent <= minx <= max_x_extent
        and -max_x_extent <= maxx <= max_x_extent
        and -max_y_extent <= miny <= max_y_extent
        and -max_y_extent <= maxy <= max_y_extent
    ):
        raise ValidationError(_("Extent coordinates out of valid range for EPSG:4326"))

    if minx >= maxx or miny >= maxy:
        raise ValidationError(
            _("Invalid extent: min values must be less than max values")
        )

    return minx, miny, maxx, maxy


def get_extent_polygon(extent_str: str | None) -> Polygon:
    """Cleans the extent by ensuring it is a valid rectangle and normalizing it.

    Args:
        extent_str: Expected input is EPSG:4326 coordinates in the format "minX, minY, maxX, maxY".

    Returns:
        A normalized Polygon representing the extent in EPSG:3426.

    """
    if extent_str:
        # Return default extent if not provided
        polygon = Polygon.from_bbox(parse_extent_coords(extent_str))
    else:
        polygon = Polygon.from_bbox(DEFAULT_PROJECT_EXTENT)

    polygon.srid = 4326

    return polygon


def build_basemap_config(
    basemap_provider: str,
    basemap_style: str,
    basemap_url: str,
) -> list[BasemapConfig]:
    """Build basemap configuration list from provider/style/url inputs.

    Returns:
        List of basemap configs (empty if provider is "none").

    Raises:
        ValueError: if basemap_provider or basemap_style is unsupported,
                    or if custom provider is missing a URL.
    """
    if basemap_provider == BasemapProvider.NONE:
        return []

    if basemap_provider == BasemapProvider.OSM:
        basemap_url = OSM_URL

        if basemap_style == BasemapStyle.STANDARD:
            name = "OpenStreetMap (Standard)"
        elif basemap_style == BasemapStyle.GRAYSCALE_LIGHT:
            name = "OpenStreetMap (Grayscale Light)"
        elif basemap_style == BasemapStyle.GRAYSCALE_DARK:
            name = "OpenStreetMap (Grayscale Dark)"
        else:
            raise ValueError(
                _(f'Basemap style "{basemap_style}" is not supported for OSM.')
            )
    elif basemap_provider == BasemapProvider.CUSTOM:
        if not basemap_url:
            raise ValueError(
                _("basemap_url is required when basemap_provider is 'custom'.")
            )

        name = "Basemap"
    else:
        raise ValueError(_(f'Basemap provider "{basemap_provider}" is not supported.'))

    return [
        {
            "url": basemap_url,
            "style": basemap_style,
            "name": name,
        }
    ]


def build_seed_data(
    basemap_provider: str,
    basemap_style: str,
    basemap_url: str,
    extent_input: str | None,
    xlsform_file: UploadedFile | None,
) -> tuple[list[BasemapConfig], Polygon, dict | None]:
    """Build all seed components from raw inputs.

    Returns:
        Tuple of (basemaps_list, extent_polygon, xlsform_config or None).

    Raises:
        ValueError: on invalid basemap or extent inputs.
    """
    basemaps = build_basemap_config(basemap_provider, basemap_style, basemap_url)
    extent = get_extent_polygon(extent_input)

    xlsform_config = None
    if xlsform_file:
        xlsform_config = {
            "show_groups_as_tabs": False,
        }

    return basemaps, extent, xlsform_config
