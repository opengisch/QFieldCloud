from __future__ import annotations

from typing import TypedDict


class QgisProjectDetails(TypedDict, total=False):
    """
    The most recent data structure to be expected as a result from `qfc_worker.commands.process_projectfile` job.

    Must be kept in sync with `docker-qgis/qfc_worker/commands/process_projectfile.py`, which produces this data structure.

    WARNING: this shape has evolved over time, so feedback stored by older jobs is not guaranteed to match it.
    """

    project_name: str
    qgis_version: str
    crs: str
    extent: str
    background_color: str
    attachment_dirs: list[str]
    data_dirs: list[str]
    layers_by_id: dict[str, LayerDetails]
    ordered_layer_ids: list[str]


class LayerDetails(TypedDict):
    """Shape of a single entry in `QgisProjectDetails.layers_by_id`.

    Must be kept in sync with `docker-qgis/qfc_worker/commands/process_projectfile.py`, which produces this data structure.

    WARNING: this shape has evolved over time, so feedback stored by older jobs is not guaranteed to match it.
    """

    id: str
    name: str
    crs: str
    type: int
    type_name: str
    wkb_type: int | None
    wkb_type_name: str
    geom_type: int | None
    geom_type_name: str
    filename: str
    is_valid: bool
    is_localized: bool
    datasource: str
    error_code: str
    error_summary: str
    error_message: str
    provider_name: str
    provider_error_summary: str
    provider_error_message: str
    qfs_action: str
    qfs_cloud_action: str
    qfs_photo_naming: str
    qfs_is_geometry_locked: bool
    qfs_unsupported_source_pk: str
    qfc_source_data_pk_name: str
