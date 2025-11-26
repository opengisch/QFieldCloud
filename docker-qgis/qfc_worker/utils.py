import atexit
import gc
import hashlib
import io
import logging
import os
import re
import socket
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, NamedTuple, TypedDict, cast

from libqfieldsync.layer import LayerSource
from libqfieldsync.utils.bad_layer_handler import (
    bad_layer_handler,
    set_bad_layer_handler,
)
from qfieldcloud_sdk import sdk
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFieldConstraints,
    QgsLayerTree,
    QgsMapLayer,
    QgsMapSettings,
    QgsProject,
    QgsProjectArchive,
    QgsProviderRegistry,
    QgsZipUtils,
)
from qgis.PyQt import QtCore, QtGui
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument
from tabulate import tabulate

# Get environment variables
JOB_ID = os.environ.get("JOB_ID")

qgs_stderr_logger = logging.getLogger("QGSSTDERR")
qgs_stderr_logger.setLevel(logging.DEBUG)
qgs_msglog_logger = logging.getLogger("QGSMSGLOG")
qgs_msglog_logger.setLevel(logging.DEBUG)


def _qt_message_handler(mode, context, message):
    log_level = logging.DEBUG
    if mode == QtCore.QtDebugMsg:
        log_level = logging.DEBUG
    elif mode == QtCore.QtInfoMsg:
        log_level = logging.INFO
    elif mode == QtCore.QtWarningMsg:
        log_level = logging.WARNING
    elif mode == QtCore.QtCriticalMsg:
        log_level = logging.CRITICAL
    elif mode == QtCore.QtFatalMsg:
        log_level = logging.FATAL

    qgs_stderr_logger.log(
        log_level,
        message,
        extra={
            "time": datetime.now().isoformat(),
            "line": context.line,
            "file": context.file,
            "function": context.function,
        },
    )


QtCore.qInstallMessageHandler(_qt_message_handler)


def _write_log_message(message, tag, level):
    log_level = logging.DEBUG

    # in 3.16 it was Qgis.None, but since None is a reserved keyword, it was inaccessible
    try:
        Qgis.NoLevel
    except Exception:
        Qgis.NoLevel = 4

    if level == Qgis.NoLevel:
        log_level = logging.DEBUG
    elif level == Qgis.Info:
        log_level = logging.INFO
    elif level == Qgis.Success:
        log_level = logging.INFO
    elif level == Qgis.Warning:
        log_level = logging.WARNING
    elif level == Qgis.Critical:
        log_level = logging.CRITICAL

    qgs_msglog_logger.log(
        log_level,
        message,
        extra={
            "time": datetime.now().isoformat(),
            "tag": tag,
        },
    )


QGISAPP: QgsApplication | None = None


qgis_project_readonly_flags = (
    Qgis.ProjectReadFlags()
    | Qgis.ProjectReadFlag.ForceReadOnlyLayers
    | Qgis.ProjectReadFlag.DontLoadLayouts
    | Qgis.ProjectReadFlag.DontLoad3DViews
    | Qgis.ProjectReadFlag.DontLoadProjectStyles
)


def start_app() -> str:
    """
    Will start a QgsApplication and call all initialization code like
    registering the providers and other infrastructure. It will not load
    any plugins.

    You can always get the reference to a running app by calling `QgsApplication.instance()`.

    The initialization will only happen once, so it is safe to call this method repeatedly.

        Returns
        -------
        str: QGIS app version that was started.
    """
    global QGISAPP

    extra_envvars = os.environ.get("QFIELDCLOUD_EXTRA_ENVVARS", "[]")

    logging.info(f"Available user defined environment variables: {extra_envvars}")

    if QGISAPP is None:
        logging.info(
            f"Starting QGIS app version {Qgis.versionInt()} ({Qgis.devVersion()})..."
        )
        argvb = []

        # Note: QGIS_PREFIX_PATH is evaluated in QgsApplication -
        # no need to mess with it here.
        gui_flag = False
        QGISAPP = QgsApplication(argvb, gui_flag)

        QtCore.qInstallMessageHandler(_qt_message_handler)
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = tempfile.mkdtemp("", "QGIS_CONFIG")
        QGISAPP.initQgis()

        QtCore.qInstallMessageHandler(_qt_message_handler)
        QgsApplication.messageLog().messageReceived.connect(_write_log_message)

        # make sure the app is closed, otherwise the container exists with non-zero
        @atexit.register
        def exitQgis():
            stop_app()

        logging.info("QGIS app started!")

    # we set the `bad_layer_handler` and assume we always have only one single `QgsProject` instance within the job's life
    QgsProject.instance().setBadLayerHandler(bad_layer_handler)

    return Qgis.version()


def stop_app():
    """
    Cleans up and exits QGIS
    """
    global QGISAPP

    # note that if this function is called from @atexit.register, the globals are cleaned up
    if "QGISAPP" not in globals():
        return

    QgsProject.instance().clear()

    if QGISAPP is not None:
        logging.info("Stopping QGIS app…")

        # NOTE we force run the GB just to make sure there are no dangling QGIS objects when we delete the QGIS application
        gc.collect()

        QGISAPP.exitQgis()

        del QGISAPP

        logging.info("Deleted QGIS app!")


def open_qgis_project(
    the_qgis_file_name: str,
    force_reload: bool = False,
    disable_feature_count: bool = False,
    flags: Qgis.ProjectReadFlags = Qgis.ProjectReadFlags(),
) -> QgsProject:
    logging.info(f'Loading the QGIS file "{the_qgis_file_name}"…')

    if not Path(the_qgis_file_name).exists():
        raise FileNotFoundError(f"File not found: {the_qgis_file_name}")

    project = QgsProject.instance()

    assert project

    if project.fileName() == str(the_qgis_file_name) and not force_reload:
        logging.info(
            f'Skip loading the QGIS file "{the_qgis_file_name}", it is already loaded'
        )
        return project

    if disable_feature_count:
        strip_feature_count_from_project_xml(the_qgis_file_name)

    with set_bad_layer_handler(project):
        if not project.read(str(the_qgis_file_name), flags):
            logging.error(f'Failed to load the QGIS file "{the_qgis_file_name}"!')

            project.setFileName("")

            raise Exception(
                f"Unable to open project with QGIS file: {the_qgis_file_name}"
            )

    logging.info("Project loaded.")

    return project


def open_qgis_project_as_readonly(
    the_qgis_file_name: str,
    force_reload: bool = False,
    disable_feature_count: bool = False,
) -> QgsProject:
    return open_qgis_project(
        the_qgis_file_name,
        force_reload=force_reload,
        disable_feature_count=disable_feature_count,
        flags=qgis_project_readonly_flags,
    )


class OpenQgisProjectTemporarilySettings(TypedDict):
    layer_tree: QgsLayerTree | None
    output_size: tuple[int, int]


class OpenQgisProjectTemporarilyDetailsInner(TypedDict):
    background_color: str
    extent: str
    map_settings: QgsMapSettings


class OpenQgisProjectTemporarilyDetails(OpenQgisProjectTemporarilyDetailsInner):
    project: QgsProject


def open_qgis_project_temporarily(
    qgis_filename: str,
) -> OpenQgisProjectTemporarilyDetails:
    """Opens a QGIS project temporarily to extract some details from it and returns the details and the project instance.

    Args:
        qgis_filename: the path of the QGIS project file (.qgs or .qgz)

    Returns:
        a dictionary with the project details and the project instance
    """
    map_settings = QgsMapSettings()

    def on_project_read_wrapper(
        tmp_project: QgsProject,
        map_settings: QgsMapSettings,
        settings: OpenQgisProjectTemporarilySettings,
        details: OpenQgisProjectTemporarilyDetailsInner,
    ) -> Callable[[QDomDocument], None]:
        def on_project_read(doc: QDomDocument) -> None:
            r, _success = tmp_project.readNumEntry("Gui", "/CanvasColorRedPart", 255)
            g, _success = tmp_project.readNumEntry("Gui", "/CanvasColorGreenPart", 255)
            b, _success = tmp_project.readNumEntry("Gui", "/CanvasColorBluePart", 255)
            background_color = QColor(r, g, b)
            map_settings.setBackgroundColor(background_color)

            nodes = doc.elementsByTagName("mapcanvas")

            for i in range(nodes.size()):
                node = nodes.item(i)
                element = node.toElement()
                if (
                    element.hasAttribute("name")
                    and element.attribute("name") == "theMapCanvas"
                ):
                    map_settings.readXml(node)

            map_settings.setRotation(0)
            map_settings.setTransformContext(tmp_project.transformContext())
            map_settings.setPathResolver(tmp_project.pathResolver())

            output_size = settings["output_size"]
            map_settings.setOutputSize(QSize(output_size[0], output_size[1]))

            layer_tree = settings["layer_tree"]
            if layer_tree:
                map_settings.setLayers(reversed(list(layer_tree.customLayerOrder())))

            if map_settings.extent().isEmpty():
                # set to full extent if empty
                map_settings.setExtent(map_settings.fullExtent())

            details["background_color"] = background_color.name()
            details["extent"] = map_settings.extent().asWktPolygon()
            details["map_settings"] = map_settings

        return on_project_read

    details = cast(OpenQgisProjectTemporarilyDetailsInner, {})
    tmp_project = QgsProject()
    tmp_layer_tree = tmp_project.layerTreeRoot()

    tmp_project.readProject.connect(
        on_project_read_wrapper(
            tmp_project,
            map_settings,
            {
                "layer_tree": tmp_layer_tree,
                "output_size": (100, 100),
            },
            details,
        )
    )
    tmp_project.read(qgis_filename, qgis_project_readonly_flags)

    details = cast(
        OpenQgisProjectTemporarilyDetails,
        {
            **details,
            "project": tmp_project,
        },
    )

    return details


def strip_feature_count_from_project_xml(the_qgis_file_name: str) -> None:
    """Rewrites project XML file with feature count disabled.

    Args:
        the_qgis_file_name: filename of the QGIS filename (.qgs or .qgz)
    """
    archive = None
    xml_file = the_qgis_file_name
    if QgsZipUtils.isZipFile(the_qgis_file_name):
        logging.info("The QGIS file is zipped as .qgz, unzipping…")

        archive = QgsProjectArchive()

        if archive.unzip(the_qgis_file_name):
            logging.info("The QGIS file is unzipped successfully!")
            xml_file = archive.projectFile()
        else:
            logging.error("The QGIS file is unzipping failed!")

            raise Exception(f"Failed to unzip {the_qgis_file_name} file!")

    logging.info("Parsing QGIS file XML…")

    tree = ET.parse(xml_file)
    root = tree.getroot()

    logging.info("QGIS project parsed!")

    for node in root.findall(".//legendlayer"):
        node.set("showFeatureCount", "0")

    for node in root.findall(
        './/layer-tree-layer/customproperties/Option[@type="Map"]/Option[@name="showFeatureCount"]'
    ):
        node.set("value", "0")

    logging.info("Writing the QGIS project XML into a file…")

    if archive:
        tmp_filename = tempfile.NamedTemporaryFile().name
        tree.write(tmp_filename, short_empty_elements=False)

        if not archive.clearProjectFile():
            raise Exception("Failed to clear project path from the archive!")

        if not Path(tmp_filename).rename(xml_file):
            raise Exception("Failed to move the temp xml file into archive dir!")

        archive.addFile(xml_file)

        if not archive.zip(the_qgis_file_name):
            raise Exception(f"Failed to zip QGIS file {the_qgis_file_name}!")
    else:
        tree.write(xml_file, short_empty_elements=False)

    logging.info("The QGIS file re-written!")


def download_project(
    project_id: str, destination: Path | None = None, skip_attachments: bool = True
) -> Path:
    """Download the files in the project "working" directory from the S3
    Storage into a temporary directory. Returns the directory path"""
    logging.info("Preparing a temporary directory for project files…")

    if not destination:
        # Create a temporary directory
        destination = Path(tempfile.mkdtemp())

    # Create a local working directory
    working_dir = destination.joinpath("files")
    working_dir.mkdir(parents=True)

    client = sdk.Client()
    files = client.list_remote_files(project_id)

    if skip_attachments:
        files = [file for file in files if not file["is_attachment"]]

    logging.info("Downloading project files…")

    client.download_files(
        files,
        project_id,
        sdk.FileTransferType.PROJECT,
        str(working_dir),
        filter_glob="*",
        throw_on_error=True,
        show_progress=False,
    )

    logging.info("Downloading project files finished!")

    list_local_files(project_id, working_dir)

    return destination


def upload_package(project_id: str, package_dir: Path) -> None:
    client = sdk.Client()
    list_local_files(project_id, package_dir)

    logging.info("Uploading packaged project files…")

    client.upload_files(
        project_id,
        sdk.FileTransferType.PACKAGE,
        str(package_dir),
        filter_glob="*",
        throw_on_error=True,
        show_progress=False,
        job_id=JOB_ID,
    )

    logging.info("Uploading packaged project files finished!")


def upload_project(project_id: str, project_dir: Path) -> None:
    """Upload the files from the `project_dir` to the permanent file storage."""
    client = sdk.Client()
    list_local_files(project_id, project_dir)

    logging.info("Uploading project files…")

    client.upload_files(
        project_id,
        sdk.FileTransferType.PROJECT,
        str(project_dir),
        filter_glob="*",
        throw_on_error=True,
        show_progress=False,
    )

    logging.info("Uploading packaged project files finished!")


def list_local_files(project_id: str, project_dir: Path):
    client = sdk.Client()

    logging.info("Getting project files list…")

    files = client.list_local_files(str(project_dir), "*")
    if files:
        logging.info(
            f'Local files list for project "{project_id}":\n{files_list_to_string(files)}',
        )
    else:
        logging.info(
            f'Local files list for project "{project_id}": empty!',
        )


def is_localhost(hostname: str, port: int | None = None) -> bool:
    """returns True if the hostname points to the localhost, otherwise False."""
    if port is None:
        port = 22  # no port specified, lets just use the ssh port

    try:
        hostname = socket.getfqdn(hostname)

        if hostname in ("localhost", "0.0.0.0"):
            return True

        localhost = socket.gethostname()
        localaddrs = socket.getaddrinfo(localhost, port)
        targetaddrs = socket.getaddrinfo(hostname, port)

        for _family, _socktype, _proto, _canonname, sockaddr in localaddrs:
            for _rfamily, _rsocktype, _rproto, _rcanonname, rsockaddr in targetaddrs:
                if rsockaddr[0] == sockaddr[0]:
                    return True

        return False
    except Exception:
        return False


def has_ping(hostname: str) -> bool:
    ping = subprocess.Popen(
        ["ping", "-c", "1", "-w", "5", hostname],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    out, error = ping.communicate()

    return not bool(error) and "100% packet loss" not in out.decode("utf8")


def get_layer_filename(layer: QgsMapLayer) -> str | None:
    metadata = QgsProviderRegistry.instance().providerMetadata(
        layer.dataProvider().name()
    )

    if metadata is not None:
        decoded = metadata.decodeUri(layer.source())
        if "path" in decoded:
            return decoded["path"]

    return None


def extract_project_details(project: QgsProject) -> dict[str, str]:
    """Extract project details"""
    map_settings = QgsMapSettings()
    details = {}

    def on_project_read(doc):
        r, _success = project.readNumEntry("Gui", "/CanvasColorRedPart", 255)
        g, _success = project.readNumEntry("Gui", "/CanvasColorGreenPart", 255)
        b, _success = project.readNumEntry("Gui", "/CanvasColorBluePart", 255)
        background_color = QtGui.QColor(r, g, b)
        map_settings.setBackgroundColor(background_color)

        details["background_color"] = background_color.name()

        nodes = doc.elementsByTagName("mapcanvas")

        for i in range(nodes.size()):
            node = nodes.item(i)
            element = node.toElement()
            if (
                element.hasAttribute("name")
                and element.attribute("name") == "theMapCanvas"
            ):
                map_settings.readXml(node)

        map_settings.setRotation(0)
        map_settings.setOutputSize(QtCore.QSize(1024, 768))

        details["extent"] = map_settings.extent().asWktPolygon()

    project.readProject.connect(on_project_read)
    project.read(project.fileName())

    details["crs"] = project.crs().authid()
    details["project_name"] = project.title()

    return details


def get_constraint_strength(
    constraint_strength: QgsFieldConstraints.ConstraintStrength,
) -> str:
    if (
        constraint_strength
        == QgsFieldConstraints.ConstraintStrength.ConstraintStrengthNotSet
    ):
        return "not_set"
    elif (
        constraint_strength
        == QgsFieldConstraints.ConstraintStrength.ConstraintStrengthHard
    ):
        return "hard"
    elif (
        constraint_strength
        == QgsFieldConstraints.ConstraintStrength.ConstraintStrengthSoft
    ):
        return "soft"
    else:
        raise NotImplementedError(f"Unknown constraint strength: {constraint_strength}")


def get_layers_data(project: QgsProject) -> dict[str, dict]:
    layers_by_id = {}

    for layer in project.mapLayers().values():
        error = layer.error()
        layer_id = layer.id()
        layer_source = LayerSource(layer)
        filename = layer_source.filename
        data_provider = layer.dataProvider()
        data_provider_source: str | None = None
        data_provider_name: str | None = None

        layer_error_summary = ""
        if error.messageList():
            layer_error_summary = error.summary()

        wkb_type = None
        if layer.type() == QgsMapLayer.VectorLayer:
            wkb_type = layer.wkbType()

        crs = None
        if layer.crs():
            crs = layer.crs().authid()

        # TODO: Move localized layer handling functionality inside libqfieldsync (ClickUp: QF-5875)
        if layer_source.is_localized_path:
            data_provider_source = bad_layer_handler.invalid_layer_sources_by_id.get(
                layer_id
            )

            if data_provider_source and "localized:" in data_provider_source:
                # TODO: refactor and extract filename splitting logic into a reusable utility.
                filename = data_provider_source.split("localized:")[-1]

                if "|" in filename:
                    filename = filename.split("|")[0]

        elif data_provider:
            data_provider_source = layer.dataProvider().uri().uri()
            data_provider_name = layer.dataProvider().name()

        if layer.type() == QgsMapLayer.VectorLayer:
            fields = []

            for field in layer.fields():
                constraints = field.constraints()

                fields.append(
                    {
                        "name": field.name(),
                        "alias": field.alias(),
                        "comment": field.comment(),
                        "type": field.typeName(),
                        "length": field.length(),
                        "precision": field.precision(),
                        "is_not_null": bool(
                            constraints.constraints()
                            & QgsFieldConstraints.Constraint.ConstraintNotNull
                        ),
                        "constraint_strength": get_constraint_strength(
                            constraints.constraintStrength(
                                QgsFieldConstraints.Constraint.ConstraintNotNull
                            )
                        ),
                        "constraint_expression": constraints.constraintExpression(),
                        "constraint_expression_description": constraints.constraintDescription(),
                        "constraint_expression_strength": get_constraint_strength(
                            constraints.constraintStrength(
                                QgsFieldConstraints.Constraint.ConstraintExpression
                            )
                        ),
                        "is_unique": bool(
                            constraints.constraints()
                            & QgsFieldConstraints.Constraint.ConstraintUnique
                        ),
                        "is_unique_strength": get_constraint_strength(
                            constraints.constraintStrength(
                                QgsFieldConstraints.Constraint.ConstraintUnique
                            )
                        ),
                        "default_value": field.defaultValueDefinition().expression(),
                        "set_default_value_on_update": field.defaultValueDefinition().applyOnUpdate(),
                        "widget_type": field.editorWidgetSetup().type(),
                        "widget_config": field.editorWidgetSetup().config(),
                    }
                )
        else:
            fields = None

        layers_by_id[layer_id] = {
            "id": layer_id,
            "name": layer.name(),
            "crs": crs,
            "wkb_type": wkb_type,
            "qfs_action": layer.customProperty("QFieldSync/action"),
            "qfs_cloud_action": layer.customProperty("QFieldSync/cloud_action"),
            "qfs_is_geometry_locked": layer.customProperty(
                "QFieldSync/is_geometry_locked"
            ),
            "qfs_photo_naming": layer.customProperty("QFieldSync/photo_naming"),
            "qfc_source_data_pk_name": layer_source.pk_attr_name,
            "qfs_unsupported_source_pk": layer.customProperty(
                "QFieldSync/unsupported_source_pk"
            ),
            "is_valid": layer.isValid(),
            "is_localized": layer_source.is_localized_path,
            "datasource": data_provider_source,
            "type": layer.type(),
            "type_name": layer.type().name,
            "error_code": "no_error",
            "error_summary": layer_error_summary,
            "error_message": layer.error().message(),
            "filename": filename,
            "provider_name": data_provider_name,
            "provider_error_summary": None,
            "provider_error_message": None,
            "fields": fields,
        }

        if layers_by_id[layer_id]["is_valid"]:
            continue

        if data_provider:
            data_provider_error = data_provider.error()

            if data_provider.isValid():
                # there might be another reason why the layer is not valid, other than the data provider
                layers_by_id[layer_id]["error_code"] = "invalid_layer"
            else:
                if layer_source.is_localized_path:
                    layers_by_id[layer_id]["error_code"] = "localized_dataprovider"
                else:
                    layers_by_id[layer_id]["error_code"] = "invalid_dataprovider"

            layers_by_id[layer_id]["provider_error_summary"] = ""
            if data_provider_error.messageList():
                layers_by_id[layer_id]["provider_error_summary"] = (
                    data_provider_error.summary()
                )

            layers_by_id[layer_id]["provider_error_message"] = (
                data_provider_error.message()
            )

            if not layers_by_id[layer_id]["provider_error_summary"]:
                service = data_provider.uri().service()
                if service:
                    layers_by_id[layer_id]["provider_error_summary"] = (
                        f'Unable to connect to service "{service}".'
                    )

                host = data_provider.uri().host()

                port = None
                if data_provider.uri().port():
                    port = int(data_provider.uri().port())

                if host and (is_localhost(host, port) or has_ping(host)):
                    layers_by_id[layer_id]["provider_error_summary"] = (
                        f'Unable to connect to host "{host}".'
                    )

                path = layer_source.metadata.get("path")
                if path and not os.path.exists(path):
                    layers_by_id[layer_id]["error_summary"] = f'File "{path}" missing.'

        else:
            layers_by_id[layer_id]["error_code"] = "missing_dataprovider"
            layers_by_id[layer_id]["provider_error_summary"] = (
                "No data provider available"
            )

    return layers_by_id


def get_file_size(filename: str) -> int:
    return Path(filename).stat().st_size


def get_file_md5sum(filename: str) -> str:
    BLOCKSIZE = 65536
    hasher = hashlib.md5()

    with open(filename, "rb") as f:
        chunk = f.read(BLOCKSIZE)
        while chunk:
            hasher.update(chunk)
            chunk = f.read(BLOCKSIZE)

    return hasher.hexdigest()


def files_list_to_string(files: list[dict[str, Any]]) -> str:
    table = [
        [
            d["name"],
            get_file_size(d["absolute_filename"]),
            get_file_md5sum(d["absolute_filename"]),
        ]
        for d in sorted(files, key=lambda f: f["name"])
    ]
    return tabulate(
        table,
        headers=["Name", "Size", "MD5 Checksum"],
    )


def layers_data_to_string(layers_by_id: dict[str, dict]) -> str:
    # Print layer check results
    table = [
        [
            d["name"],
            f"...{d['id'][-6:]}",
            d["type_name"],
            d["is_valid"],
            d["error_code"],
            d["error_summary"],
            d["provider_error_summary"],
        ]
        for d in layers_by_id.values()
    ]

    output = ""
    output += tabulate(
        table,
        headers=[
            "Layer Name",
            "Layer Id",
            "Type",
            "Is Valid",
            "Status",
            "Error Summary",
            "Provider Summary",
        ],
    )
    output += "\n\nDetailed layers info:"

    for layer_data in layers_by_id.values():
        output += "\n"

        if not layer_data["is_valid"]:
            output += f"\nLayer '{layer_data['name']}' ({layer_data['id']}) is invalid."

            continue

        if layer_data["type_name"] != "Vector":
            output += f"\nLayer '{layer_data['name']}' ({layer_data['id']}) is valid."

            continue

        output += (
            f"\nLayer '{layer_data['name']}' ({layer_data['id']}) is valid. Fields:\n"
        )

        fields_data = layer_data.get("fields") or []
        fields_table = [
            [
                f["name"],
                f["type"],
                f["length"],
                f["precision"],
                f["is_not_null"],
                f["alias"],
            ]
            for f in fields_data
        ]

        output += tabulate(
            fields_table,
            headers=[
                "Field Name",
                "Type",
                "Length",
                "Precision",
                "Is Not Null",
                "Alias",
            ],
        )

    return output


class RedactingFormatter(logging.Formatter):
    """Filter out sensitive information such as passwords from the logs.

    Note: this is done via logging.Formatter instead of logging.Filter,
    because modified default handler formatter affects all existing loggers,
    while this is not the case for filters.
    """

    def __init__(self, *args, **kwargs) -> None:
        patterns = kwargs.pop(
            "patterns",
            [
                r"(?:password=')(.*?)(?:')",
            ],
        )
        replacement = kwargs.pop("replacement", "***")

        super().__init__(*args, **kwargs)

        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        self._replacement = replacement

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)

        if isinstance(record.args, dict):
            for k in record.args.keys():
                record.args[k] = self.redact(record.args[k])
        elif isinstance(record.args, tuple):
            record.args = tuple(self.redact(str(arg)) for arg in record.args)
        else:
            raise NotImplementedError(f"Not implemented for {type(record.args)}")

        return self.redact(msg)

    def redact(self, record: str) -> str:
        record = str(record)

        for pattern in self._patterns:
            record = re.sub(pattern, self._replacement, record)

        return record


def setup_basic_logging_config():
    """Set the default logger level to debug and set a password censoring formatter.

    This will affect all child loggers with the default handler,
    no matter if they are created before or after calling this function.
    """
    logging.basicConfig(
        level=logging.DEBUG,
    )

    formatter = RedactingFormatter(
        "%(asctime)s.%(msecs)03d %(name)-9s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    for handler in logging.root.handlers:
        handler.setFormatter(formatter)


class XmlErrorLocation(NamedTuple):
    line: int
    column: int


def get_qgis_xml_error_location(
    invalid_token_error_msg: str,
) -> XmlErrorLocation | None:
    """Get column and line numbers from the provided error message."""
    if "invalid token" not in invalid_token_error_msg.casefold():
        return None

    _, details = invalid_token_error_msg.split(":")
    line, column = details.split(",")
    _, line_number = line.strip().split(" ")
    _, column_number = column.strip().split(" ")

    return XmlErrorLocation(int(line_number), int(column_number))


def get_qgis_xml_error_context(
    invalid_token_error_msg: str, fh: io.BufferedReader
) -> str | None:
    """Get a slice of the line where the exception occurred, with all faulty occurrences sanitized."""
    location = get_qgis_xml_error_location(invalid_token_error_msg)
    if location:
        substitute = "?"
        fh.seek(0)
        for cursor_pos, line in enumerate(fh, start=1):
            if location.line == cursor_pos:
                faulty_char = line[location.column]
                suffix_slice = line[: location.column - 1]
                clean_safe_slice = suffix_slice.decode("utf-8").strip() + substitute

                return f"Unable to parse character: {repr(faulty_char)}. Replaced by '{substitute}' on line {location.line} that starts with: {clean_safe_slice}"

    return None
