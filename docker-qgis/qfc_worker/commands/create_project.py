import argparse
import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from qfieldcloud_sdk import sdk
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsHueSaturationFilter,
    QgsProject,
    QgsRasterLayer,
)
from xlsform2qgis.converter import XLSFormConverter

from qfc_worker.commands_base import QfcBaseCommand
from qfc_worker.utils import (
    get_layers_data,
    layers_data_to_string,
    open_qgis_project,
    start_app,
    stop_app,
    upload_project,
)
from qfc_worker.workflow import (
    Step,
    StepOutput,
    WorkDirPath,
    Workflow,
)

logger = logging.getLogger(__name__)


SchemaId = str


class XlsformConfigDict(TypedDict):
    show_groups_as_tabs: bool
    filename: str


class BasemapConfig(TypedDict):
    url: str
    name: str
    style: str


class ProjectSeedSettingsDict(TypedDict):
    schemaId: SchemaId
    xlsform: XlsformConfigDict | None
    basemaps: list[BasemapConfig]


class ProjectSeedDict(TypedDict):
    name: str
    crs: str
    settings: ProjectSeedSettingsDict


class BasemapStyle(str, enum.Enum):
    STANDARD = "standard"
    GRAYSCALE_LIGHT = "grayscale_light"
    GRAYSCALE_DARK = "grayscale_dark"


@dataclass
class ProjectSeedSettings:
    schemaId: SchemaId
    xlsform: XlsformConfigDict | None
    basemaps: list[BasemapConfig]


@dataclass
class ProjectSeed:
    crs: str
    name: str
    extent: list[float]
    copy_from_project: UUID | None

    settings: ProjectSeedSettings  # type: ignore
    _settings: ProjectSeedSettings = field(init=False, repr=False)

    @property  # type: ignore
    def settings(self) -> ProjectSeedSettings:
        return self._settings

    @settings.setter
    def settings(self, value: ProjectSeedSettingsDict) -> None:
        schema_id = value["schemaId"]

        if schema_id == "https://app.qfield.cloud/schemas/project-seed-20251201.json":
            self._settings = ProjectSeedSettings(**value)
        else:
            raise NotImplementedError(
                f"Project seed settings version '{value['schemaId']}' is not supported."
            )


def get_project_seed(project_id: str) -> ProjectSeed:
    client = sdk.Client()

    project_seed = client.get_project_seed(project_id)

    return ProjectSeed(**project_seed)


def get_project_seed_xlsform(
    project_id: str, project_seed: ProjectSeed, destination_dir: str
) -> Path | None:
    if not project_seed.settings.xlsform:
        logger.info("No XLSForm configured for this project seed.")

        return None

    client = sdk.Client()
    xlsform_path = client.get_project_seed_xlsform(project_id, destination_dir)

    logger.info(f"Downloaded XLSForm file to '{xlsform_path}'.")

    return xlsform_path


def _create_project_from_xlsform(
    xlsform_filename: Path | str, project_seed: ProjectSeed, tmp_project_dir: str
):
    assert project_seed.settings.xlsform is not None

    xlsform_filename = Path(tmp_project_dir).joinpath("files", xlsform_filename)

    logger.info(
        f"Checking provided XLSForm file '{xlsform_filename}' {Path(xlsform_filename).exists()} ..."
    )

    if not Path(xlsform_filename).exists():
        logger.error(
            f"The provided XLSForm file '{xlsform_filename}' does not exist, aborting."
        )

        return None

    converter = XLSFormConverter(str(xlsform_filename))

    if not converter.is_valid():
        logger.error("The provided XLSForm is invalid, aborting.")

        return None

    converter.info.connect(lambda message: logger.info(message))
    converter.warning.connect(lambda message: logger.warning(message))
    converter.error.connect(lambda message: logger.error(message))

    converter.set_groups_as_tabs(project_seed.settings.xlsform["show_groups_as_tabs"])
    converter.set_custom_title(project_seed.name)

    project_file = converter.convert(Path(tmp_project_dir).joinpath("files"))

    return project_file


def create_project_from_seed(
    project_seed: ProjectSeed, tmp_project_dir: str, xlsform_filename: str
) -> str:
    crs = QgsCoordinateReferenceSystem(project_seed.crs)

    if not crs.isValid():
        logger.warning(
            "Project extent parameter ignored, a required project CRS parameter is missing."
        )

    project_filename = None
    if project_seed.settings.xlsform:
        logger.info(f'Creating QGIS project from XLSForm from "{xlsform_filename}"...')

        project_filename = _create_project_from_xlsform(
            xlsform_filename, project_seed, tmp_project_dir
        )

        if project_filename is None:
            logger.info(
                "Failed to create project from XLSForm. Creating empty QGIS project..."
            )
        else:
            project_filename = Path(project_filename)

    else:
        logger.info("Creating empty QGIS project...")

    if project_filename:
        project = open_qgis_project(str(project_filename))
    else:
        project = QgsProject.instance()
        project_filename = Path(tmp_project_dir).joinpath("files", "project.qgz")

    if project_seed.settings.basemaps:
        logger.info("Adding basemaps to the project...")

        for basemap_config in project_seed.settings.basemaps:
            layer = create_basemap_layer(basemap_config)

            if layer:
                layer_bridge = project.layerTreeRegistryBridge()
                layer_tree_root = project.layerTreeRoot()
                layer_tree_children_count = len(layer_tree_root.children())

                # sets the "state" of the layer insertion point to the end of the layer tree
                layer_bridge.setLayerInsertionPoint(
                    layer_tree_root,
                    layer_tree_children_count,
                )

                # add the layer to the project
                is_success_add = project.addMapLayer(layer)

                if is_success_add:
                    logger.info(
                        f'Successfully added basemap layer "{basemap_config["name"]}" to project.'
                    )
                else:
                    logger.warning(
                        f'Failed to add basemap layer "{basemap_config["name"]}" to project.'
                    )
            else:
                logger.warning(
                    f'Failed to create basemap layer "{basemap_config["name"]}".'
                )
    else:
        logger.info("No basemaps configured for this project seed.")

    project.setTitle(project_seed.name)
    project.setCrs(crs)

    logger.info(f"Saving QGIS project to {project_filename}...")

    project_filename.parent.mkdir(exist_ok=True, parents=True)

    project.write(str(project_filename))

    return str(project_filename)


def extract_layer_data(the_qgis_file_name: str | Path) -> dict:
    logger.info("Extracting QGIS project layer data…")

    project = open_qgis_project(str(the_qgis_file_name))
    layers_by_id: dict = get_layers_data(project)

    logger.info(
        f"QGIS project layer data\n{layers_data_to_string(layers_by_id)}",
    )

    return layers_by_id


def create_basemap_layer(basemap_config: BasemapConfig) -> QgsRasterLayer:
    layer = QgsRasterLayer(
        f"type=xyz&tilePixelRatio=1&url={basemap_config['url']}&zmax=19&zmin=0&crs=EPSG3857",
        basemap_config["name"],
        "wms",
    )

    if not layer.isValid():
        return None

    hue_saturation_filter = layer.hueSaturationFilter()

    try:
        style = BasemapStyle(basemap_config["style"])
    except ValueError:
        logger.warning(
            f"Unknown basemap style '{basemap_config['style']}', using standard style."
        )

        style = BasemapStyle.STANDARD

    if style == BasemapStyle.STANDARD:
        # do nothing extra, all is good
        pass
    elif style == BasemapStyle.GRAYSCALE_LIGHT:
        hue_saturation_filter.setGrayscaleMode(
            QgsHueSaturationFilter.GrayscaleLightness
        )
    elif style == BasemapStyle.GRAYSCALE_DARK:
        hue_saturation_filter.setGrayscaleMode(
            QgsHueSaturationFilter.GrayscaleLightness
        )
        hue_saturation_filter.setInvertColors(True)
    else:
        raise NotImplementedError(f"Basemap style '{style}' is not implemented!")

    return layer


class CloneProjectCommand(QfcBaseCommand):
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("project_id", type=UUID, help="Project ID")

    def get_workflow(self, project_id: UUID) -> Workflow:  # type: ignore
        workflow = Workflow(
            id="create_project",
            name="Create Projectfile",
            version="1.0",
            steps=[
                Step(
                    id="start_qgis_app",
                    name="Start QGIS Application",
                    method=start_app,
                    return_names=["qgis_version"],
                ),
                Step(
                    id="get_project_seed",
                    name="Get Project Seed",
                    arguments={
                        "project_id": project_id,
                    },
                    method=get_project_seed,
                    return_names=["project_seed"],
                ),
                Step(
                    id="get_project_seed_xlsform",
                    name="Get Project Seed XLSForm",
                    arguments={
                        "project_id": project_id,
                        "project_seed": StepOutput("get_project_seed", "project_seed"),
                        "destination_dir": WorkDirPath(),
                    },
                    method=get_project_seed_xlsform,
                    return_names=["xlsform_filename"],
                ),
                Step(
                    id="create_project_from_seed",
                    name="Create project from seed",
                    arguments={
                        "project_seed": StepOutput("get_project_seed", "project_seed"),
                        "tmp_project_dir": WorkDirPath(),
                        "xlsform_filename": StepOutput(
                            "get_project_seed_xlsform", "xlsform_filename"
                        ),
                    },
                    method=create_project_from_seed,
                    return_names=["qgis_project_file"],
                ),
                Step(
                    id="qgis_layers_data",
                    name="QGIS Layers Data",
                    arguments={
                        "the_qgis_file_name": StepOutput(
                            "create_project_from_seed", "qgis_project_file"
                        ),
                    },
                    method=extract_layer_data,
                    return_names=["layers_by_id"],
                    outputs=["layers_by_id"],
                ),
                Step(
                    id="upload_project_directory",
                    name="Upload Project",
                    arguments={
                        "project_id": project_id,
                        "project_dir": WorkDirPath("files"),
                    },
                    method=upload_project,
                ),
                Step(
                    id="stop_qgis_app",
                    name="Stop QGIS Application",
                    method=stop_app,
                ),
            ],
        )

        return workflow


cmd = CloneProjectCommand()

if __name__ == "__main__":
    cmd.run_from_argv()
