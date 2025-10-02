#!/usr/bin/env python3

import logging
from pathlib import Path

from libqfieldsync.offline_converter import ExportType, OfflineConverter
from libqfieldsync.offliners import OfflinerType, PythonMiniOffliner, QgisCoreOffliner
from libqfieldsync.project import ProjectConfiguration
from libqfieldsync.utils.file_utils import get_project_in_folder
from qgis.core import QgsCoordinateTransform, QgsRectangle

import qfc_worker.apply_deltas
import qfc_worker.process_projectfile
import qfc_worker.utils
from qfc_worker.utils import (
    get_layers_data,
    layers_data_to_string,
    open_qgis_project,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def call_libqfieldsync_packager(
    the_qgis_file_name: Path, package_dir: Path, offliner_type: OfflinerType
) -> Path:
    """Call `libqfieldsync` to package a project for QField"""
    logger.info("Preparing QGIS project for packaging…")

    project = open_qgis_project(str(the_qgis_file_name))

    layers = project.mapLayers()
    project_config = ProjectConfiguration(project)
    vl_extent_wkt = ""
    vl_extent = QgsRectangle()
    vl_extent_crs = project.crs()

    logger.info("Getting project area of interest…")

    if project_config.area_of_interest and project_config.area_of_interest_crs:
        vl_extent_wkt = project_config.area_of_interest
        vl_extent_crs = project_config.area_of_interest_crs
    else:
        vl_extent = QgsRectangle()
        for layer in layers.values():
            layer_extent = layer.extent()

            if layer_extent.isNull() or not layer_extent.isFinite():
                continue

            try:
                transform = QgsCoordinateTransform(layer.crs(), project.crs(), project)
                vl_extent.combineExtentWith(
                    transform.transformBoundingBox(layer_extent)
                )
            except Exception as err:
                logger.error(
                    "Failed to transform the bbox for layer {} from {} to {} CRS.".format(
                        layer.name(), layer.crs(), project.crs()
                    ),
                    exc_info=err,
                )

        if vl_extent.isNull() or not vl_extent.isFinite():
            logger.info("Failed to obtain the project extent from project layers.")

            try:
                vl_extent = QgsRectangle.fromWkt(
                    qfc_worker.utils.extract_project_details(project)["extent"]
                )
            except Exception as err:
                logger.error(
                    "Failed to get the project extent from the current map canvas.",
                    exc_info=err,
                )

        if vl_extent.isNull() or not vl_extent.isFinite():
            raise Exception("Failed to obtain the project extent.")

        # sometimes the result is a polygon whose all points are on the same line
        # this is an invalid polygon and cannot libqfieldsync does not like it
        vl_extent = vl_extent.buffered(1)
        vl_extent_wkt = vl_extent.asWktPolygon()
        vl_extent_crs = project.crs()

    logger.info(
        f"Project area of interest is `{vl_extent_wkt}` in `{vl_extent_crs}` CRS."
    )

    attachment_dirs, _ = project.readListEntry("QFieldSync", "attachmentDirs", ["DCIM"])
    data_dirs, _ = project.readListEntry("QFieldSync", "dataDirs", [])

    offliner: QgisCoreOffliner | PythonMiniOffliner
    if offliner_type == OfflinerType.QGISCORE:
        offliner = QgisCoreOffliner()
    elif offliner_type == OfflinerType.PYTHONMINI:
        offliner = PythonMiniOffliner()
    else:
        raise NotImplementedError(f"Offliner type {offliner_type} is not supported.")

    logger.info(f'Offliner set to "{offliner_type}"')

    logger.info("Packaging…")

    the_packaged_qgis_filename = package_dir.joinpath(
        f"{the_qgis_file_name.stem}_qfield.qgs"
    )
    offline_converter = OfflineConverter(
        project,
        export_filename=str(the_packaged_qgis_filename),
        area_of_interest_wkt=vl_extent_wkt,
        area_of_interest_crs=vl_extent_crs,
        attachment_dirs=attachment_dirs + data_dirs,
        offliner=offliner,
        export_type=ExportType.Cloud,
        create_basemap=False,
    )

    # Disable the basemap generation because it needs the processing
    # plugin to be installed
    offline_converter.project_configuration.create_base_map = False
    offline_converter.convert(reload_original_project=False)

    logger.info("Packaging finished!")

    assert str(the_packaged_qgis_filename) == get_project_in_folder(str(package_dir))

    if Path(the_packaged_qgis_filename).stat().st_size == 0:
        raise Exception("The packaged QGIS project file is empty.")

    return the_packaged_qgis_filename


def extract_layer_data(the_qgis_file_name: str | Path) -> dict:
    logger.info("Extracting QGIS project layer data…")

    project = open_qgis_project(str(the_qgis_file_name))
    layers_by_id: dict = get_layers_data(project)

    logger.info(
        f"QGIS project layer data\n{layers_data_to_string(layers_by_id)}",
    )

    return layers_by_id
