from typing import Any
from urllib.parse import parse_qs, urlparse

from qfieldcloud.core.models import Project


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
    """Returns None if project details or layers details are not available"""

    if not project.project_details:
        return False

    layers_by_id: dict[str, dict[str, Any]] = project.project_details.get(
        "layers_by_id"
    )

    if layers_by_id is None:
        return False

    has_online_vector_layers = False

    for layer_data in layers_by_id.values():
        # NOTE QGIS 3.30.x returns "Vector", while previous versions return "VectorLayer"
        is_vector_layer = layer_data.get("type_name") in (
            "VectorLayer",
            "Vector",
        )
        layer_filename = layer_data.get("filename", "")
        provider_name = layer_data.get("provider_name", "")

        if not is_vector_layer:
            continue

        # memory layers are not having a filename, but should not be considered online
        if provider_name == "memory":
            continue

        # virtual layers are not having a filename, but they should not be considered online, unless they have embedded layers.
        # NOTE even though the embedded layers could be file based, we consider virtual layers with embedded layers as online datasets.
        # TODO @suricactus: QF-6870 Allow virtual layers with file based embedded layers in all plans, see https://app.clickup.com/t/2192114/QF-6870
        if provider_name == "virtual" and not is_virtual_layer_with_embedded_layers(
            layer_data.get("datasource", "")
        ):
            continue

        # having a filename means the project is using online datasets
        if layer_filename:
            continue

        has_online_vector_layers = True
        break

    return has_online_vector_layers
