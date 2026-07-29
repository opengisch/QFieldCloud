from urllib.parse import parse_qs, urlparse

from qfieldcloud.project.enums import QgsLayerType
from qfieldcloud.project.models import Project


def is_virtual_layer_with_embedded_layers(datasource: str) -> bool:
    """Check if a virtual layer source has embedded layers.

    The source is expected to be a valid virtual layer source string.

    Example of a virtual layer source with embedded layers:

    - "?query=SELECT%20*%20FROM%20points"
    - "?layer=ogr:%2Fhome%2Fuser%2Ftestdata.gpkg%7Clayername%3Dpoints_xy:points_xy:&layer=ogr:%2Fhome%2Fuser%2Ftestdata.gpkg%7Clayername%3Dpoints_xy:points_xy:&query=SELECT%20*%20FROM%20points"
    """

    url = urlparse(datasource)
    query = parse_qs(url.query)

    has_embedded_layers = "layer" in query and len(query["layer"]) > 0

    return has_embedded_layers


def has_online_vector_data(project: Project) -> bool:
    """Returns `False` if the project has no associated `QgisProject`, or no online vector layers"""

    qgis_project = getattr(project, "qgis_project", None)

    if qgis_project is None:
        return False

    vector_layers = qgis_project.layers.filter(layer_type=QgsLayerType.Vector)

    for layer in vector_layers:
        # memory layers are not having a filename, but should not be considered online
        if layer.provider_name == "memory":
            continue

        # virtual layers are not having a filename, but they should not be considered online, unless they have embedded layers.
        # NOTE even though the embedded layers could be file based, we consider virtual layers with embedded layers as online datasets.
        # TODO @suricactus: QF-6870 Allow virtual layers with file based embedded layers in all plans, see https://app.clickup.com/t/2192114/QF-6870
        if (
            layer.provider_name == "virtual"
            and not is_virtual_layer_with_embedded_layers(layer.datasource or "")
        ):
            continue

        # having a filename means the project is using online datasets
        if layer.file_name:
            continue

        return True

    return False


def get_qgis_major_version(version: str) -> int:
    """Extract the major version number from a QGIS version string.

    The version string is expected to be in the format "X.Y.Z" or "X.Y.Z-rcN", where X is the major version number.

    Example:
    - "3.30.0" -> 3
    - "3.30.0-rc1" -> 3
    - "4.0.0" -> 4
    """

    try:
        major_version_str = version.split(".")[0]
        major_version = int(major_version_str)
        return major_version
    except (IndexError, ValueError):
        raise ValueError(f"Invalid QGIS version string: {version}")
