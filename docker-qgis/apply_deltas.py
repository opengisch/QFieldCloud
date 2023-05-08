#!/usr/bin/env python3

import re
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, cast

try:
    # 3.8
    from typing import TypedDict
except ImportError:
    # 3.7
    from typing_extensions import TypedDict

import argparse
import json
import logging
import shutil
import textwrap
import traceback
from functools import lru_cache
from pathlib import Path

import jsonschema

# pylint: disable=no-name-in-module
from qgis.core import (
    QgsDataSourceUri,
    QgsExpression,
    QgsFeature,
    QgsGeometry,
    QgsMapLayer,
    QgsMapLayerType,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorLayer,
    QgsVectorLayerEditPassthrough,
    QgsVectorLayerUtils,
)
from qgis.PyQt.QtCore import QCoreApplication, QDate, QDateTime, Qt, QTime

logger = logging.getLogger(__name__)
# /LOGGER

# TYPE DEFINITIONS
WKT = str
Uuid = str
FeaturePk = str
LayerId = str


class BaseOptions(TypedDict):
    cmd0: Callable
    project: str


class DeltaOptions(BaseOptions):
    delta_file: Optional[str]
    delta_contents: Optional[Dict]
    delta_log: Optional[str]
    overwrite_conflicts: bool
    inverse: bool
    transaction: bool


class DeltaMethod(str, Enum):
    def __str__(self):
        return str(self.value)

    CREATE = "create"
    PATCH = "patch"
    DELETE = "delete"


class DeltaExceptionType(str, Enum):
    def __str__(self):
        return str(self.value)

    Error = "ERROR"
    IO = "IO"
    Conflict = "CONFLICT"


class DeltaStatus(str, Enum):
    def __str__(self):
        return str(self.value)

    Applied = "status_applied"
    Conflict = "status_conflict"
    ApplyFailed = "status_apply_failed"
    UnknownError = "status_unknown_error"


class DeltaFeature(TypedDict):
    geometry: Optional[WKT]
    attributes: Optional[Dict[str, Any]]
    file_sha256: Optional[Dict[str, str]]


class Delta(TypedDict):
    id: Uuid
    localFk: FeaturePk
    sourceFk: FeaturePk
    localLayerId: LayerId
    sourceLayerId: LayerId
    method: DeltaMethod
    old: DeltaFeature
    new: DeltaFeature


class DeltaFile:
    def __init__(
        self,
        delta_file_id: str,
        project_id: str,
        version: str,
        deltas: List[Union[Dict, Delta]],
        files: List[str],
        client_pks: Dict[str, str],
    ):
        self.id = delta_file_id
        self.project_id = project_id
        self.version = version
        self.files = files
        self.client_pks = client_pks
        self.deltas: List[Delta] = []

        for d in deltas:
            self.deltas.append(cast(Delta, d))


# /TYPE DEFINITIONS


# EXCEPTION DEFINITIONS\
class DeltaException(Exception):
    def __init__(
        self,
        msg: str,
        e_type: DeltaExceptionType = DeltaExceptionType.Error,
        delta_file_id: str = None,
        layer_id: str = None,
        delta_idx: int = None,
        delta_id: str = None,
        feature_pk: str = None,
        modified_pk: str = None,
        conflicts: List[str] = None,
        method: DeltaMethod = None,
        provider_errors: str = None,
        descr: str = None,
    ):
        super(DeltaException, self).__init__(msg)
        self.e_type = e_type
        self.delta_file_id = delta_file_id
        self.layer_id = layer_id
        self.delta_idx = delta_idx
        self.delta_id = delta_id
        self.feature_pk = feature_pk
        self.modified_pk = modified_pk
        self.method = method
        self.conflicts = conflicts
        self.provider_errors = provider_errors
        self.descr = descr


class FeatureNotFoundError(Exception):
    ...


class DoublicateFeatureError(Exception):
    ...


# /EXCEPTION DEFINITIONS


BACKUP_SUFFIX = ".qfieldcloudbackup"
DELTA_LOG = []


def project_decorator(f):
    def wrapper(opts: BaseOptions, *args, **kw):
        project = QgsProject.instance()
        project.setAutoTransaction(opts["transaction"])
        project.read(opts.get("project_filename", opts["project"]))

        return f(project, opts, *args, **kw)  # type: ignore

    return wrapper


def wkt_nan_to_zero(wkt: WKT) -> WKT:
    """Support of `nan` values is non-standard in WKT.

    Since it is poorly supported on QGIS and other FOSS tools, it's safer to convert the `nan` values to 0s for now. See https://github.com/qgis/QGIS/pull/47034/ .

    Args:
        wkt (WKT): wkt that might contain `nan` values

    Returns:
        WKT: WKT with `nan` values replaced with `0`s
    """
    old_wkt = wkt
    new_wkt = re.sub(r"\bnan\b", "0", wkt, flags=re.IGNORECASE)

    if old_wkt != new_wkt:
        logger.info(f"Replaced nan values with 0s for {wkt=}")

    return new_wkt


def get_geometry_from_delta(
    delta_feature: DeltaFeature, layer: QgsVectorLayer
) -> Optional[QgsGeometry]:
    """Converts the `geometry` WKT from the `DeltaFeature` to a `QgsGeometry` instance.

    Args:
        delta_feature (DeltaFeature): delta feature
        layer (QgsVectorLayer): layer the feature is part of

    Raises:
        DeltaException

    Returns:
        Optional[QgsGeometry]: the parsed `QgsGeometry`. Might be invalid geometry. Returns `None` if no geometry has been modified.
    """
    geometry = None

    if "geometry" in delta_feature:
        if delta_feature["geometry"] is None:
            # create an invalid geometry to indicate that the geometry has been deleted
            geometry = QgsGeometry()
        else:
            wkt = delta_feature["geometry"].strip()

            if not isinstance(wkt, str):
                raise DeltaException(
                    f"The provided geometry is of type {type(wkt)} which is neither null nor a WKT string."
                )

            if len(wkt) == 0:
                raise DeltaException("Empty WKT string!")

            wkt = wkt_nan_to_zero(wkt)
            geometry = QgsGeometry.fromWkt(wkt)

            # TODO consider also checking for `isEmpty()`. Not enabling it for now.
            if geometry.isNull():
                raise DeltaException(f"Null geometry from {wkt=}")

            # E.g. Shapefile might report a `Polygon` geometry, even though it is a `MultiPolygon`
            if geometry.type() != layer.geometryType():
                logger.info(
                    f"The provided geometry type {geometry.type()} differs from the layer geometry type {layer.geometryType()} for {wkt=}"
                )

    return geometry


def delta_apply(
    project_filename: Path,
    delta_filename: Path,
    inverse: bool,
    overwrite_conflicts: bool,
):
    DELTA_LOG.clear()

    project = QgsProject.instance()
    logging.info(f'Loading project file "{project_filename}"...')
    project.read(str(project_filename))

    logging.info(f'Loading delta file "{delta_filename}"...')
    delta_file = delta_file_file_loader({"delta_file": delta_filename})  # type: ignore

    if not delta_file:
        raise Exception("Missing delta file")

    all_applied = apply_deltas_without_transaction(
        project, delta_file, inverse, overwrite_conflicts
    )

    project.clear()

    if not all_applied:
        logger.info("Some deltas have not been applied")

    delta_log_copy = [*DELTA_LOG]
    DELTA_LOG.clear()

    return delta_log_copy


@project_decorator
def cmd_delta_apply(project: QgsProject, opts: DeltaOptions) -> bool:
    accepted_state = None
    deltas = None
    has_uncaught_errors = False

    try:
        del DELTA_LOG[:]
        deltas = load_delta_file(opts)

        if opts["transaction"]:
            raise NotImplementedError(
                "Please check apply_deltas(project, deltas) and upgrade it, if needed"
            )
            # accepted_state = apply_deltas(project, deltas, inverse=opts['inverse'], overwrite_conflicts=opts['overwrite_conflicts'])
        else:
            accepted_state = apply_deltas_without_transaction(
                project,
                deltas,
                inverse=opts["inverse"],
                overwrite_conflicts=opts["overwrite_conflicts"],
            )

        project.clear()

    except Exception:
        exception_str = traceback.format_exc()
        logger.error("An unknown exception has occurred, check the deltalog carefully")
        logger.exception(exception_str)

        has_uncaught_errors = True

    deltas_count = len(deltas.deltas) if deltas is not None else "?"

    if accepted_state is None:
        logger.info(
            f"Uncaught exception occurred while trying to apply {deltas_count} deltas. "
            "Check the delta log if they have been processed and what is their status"
        )
    elif accepted_state:
        logger.info(f"All {deltas_count} deltas have been applied successfully")
    else:
        logger.info(
            f"Some of the {deltas_count} deltas have not been applied. "
            "Check the delta log if they have been processed and what is their status"
        )
    print("Delta log file contents:")
    print("========================")
    print(json.dumps(DELTA_LOG, indent=2, sort_keys=True, default=str))
    print("========================")

    if opts.get("delta_log"):
        with open(opts["delta_log"], "w") as f:
            json.dump(DELTA_LOG, f, indent=2, sort_keys=True, default=str)

    return has_uncaught_errors


@project_decorator
def cmd_backup_cleanup(project: QgsProject, opts: BaseOptions):
    for layer_id in project.mapLayers():
        layer = project.mapLayer(layer_id)

        assert layer

        if layer.type() != QgsMapLayerType.VectorLayer:
            continue

        backup_layer_path = get_backup_path(get_layer_path(layer))

        if backup_layer_path.exists():
            backup_layer_path.unlink()


@project_decorator
def cmd_backup_rollback(project: QgsProject, opts: BaseOptions):
    for layer_id in project.mapLayers():
        layer = project.mapLayer(layer_id)

        assert layer

        if layer.type() != QgsMapLayerType.VectorLayer:
            continue

        layer_path = get_layer_path(layer)
        backup_layer_path = get_backup_path(layer_path)

        assert layer_path.exists()

        if backup_layer_path.exists():
            backup_layer_path.unlink()


@lru_cache(maxsize=128)
def get_json_schema_validator() -> jsonschema.Draft7Validator:
    """Creates a JSON schema validator to check whether the provided delta
    file is valid. The function result is cached.

    Returns:
        jsonschema.Draft7Validator -- JSON Schema validator
    """
    with open("./schemas/deltafile_01.json") as f:
        schema_dict = json.load(f)

    jsonschema.Draft7Validator.check_schema(schema_dict)

    return jsonschema.Draft7Validator(schema_dict)


def delta_file_args_loader(args: DeltaOptions) -> Optional[DeltaFile]:
    """Get delta file contents as a dictionary passed in the args. Mostly used for testing.

    Arguments:
        args {DeltaOptions} -- main options

    Returns:
        Optional[DeltaFile] -- loaded delta file on success, otherwise none
    """
    if "delta_contents" not in args:
        return None

    obj = args["delta_contents"]
    get_json_schema_validator().validate(obj)
    delta_file = DeltaFile(
        obj["id"],
        obj["project"],
        obj["version"],
        obj["deltas"],
        obj["files"],
        obj["clientPks"],
    )

    return delta_file


def delta_file_file_loader(args: DeltaOptions) -> Optional[DeltaFile]:
    """Get delta file contents from a filesystem file.

    Arguments:
        args {DeltaOptions} -- main options

    Returns:
        Optional[DeltaFile] -- loaded delta file on success, otherwise none
    """
    if not isinstance(args.get("delta_file"), str):
        return None

    delta_file_path = Path(args["delta_file"])  # type: ignore
    delta_file: DeltaFile

    with delta_file_path.open("r") as f:
        obj = json.load(f)
        get_json_schema_validator().validate(obj)
        delta_file = DeltaFile(
            obj["id"],
            obj["project"],
            obj["version"],
            obj["deltas"],
            obj["files"],
            obj["clientPks"],
        )

        # NOTE Sometimes QField does not fill the `sourceLayerId` field
        # In recent QGIS versions, offline editing replaces the data source of the layers, so the layer ids do not change
        # See https://github.com/opengisch/qfieldcloud/issues/415#issuecomment-1322922349
        for delta in delta_file.deltas:
            if delta["sourceLayerId"] == "" and delta["localLayerId"] != "":
                delta["sourceLayerId"] = delta["localLayerId"]
                logger.warning(
                    "Patching project %s delta's empty sourceLayerId from localLayerId",
                    delta_file.project_id,
                )

    return delta_file


def load_delta_file(args: DeltaOptions) -> DeltaFile:
    """Loads delta file, using the provided {args}.

    Arguments:
        args {DeltaOptions} -- main options

    Returns:
        DeltaFile -- the loaded deltafile
    """
    deltas: Optional[DeltaFile] = None

    delta_file_loaders = [
        delta_file_args_loader,
        delta_file_file_loader,
    ]

    for delta_file_loader in delta_file_loaders:
        deltas = delta_file_loader(args)

        if deltas is not None:
            break

    assert deltas is not None, "Unable to load deltas"

    return deltas


def apply_deltas_without_transaction(
    project: QgsProject,
    delta_file: DeltaFile,
    inverse: bool = False,
    overwrite_conflicts: bool = False,
) -> bool:
    has_applied_all_deltas = True

    # apply deltas on each individual layer
    for idx, delta in enumerate(delta_file.deltas):
        delta_status = DeltaStatus.Applied
        layer_id: str = delta.get("sourceLayerId")
        layer: QgsVectorLayer = project.mapLayer(layer_id)
        feature = QgsFeature()

        try:
            if not isinstance(layer, QgsVectorLayer):
                raise DeltaException(f'No layer with id "{layer_id}"')

            if not layer.isValid():
                raise DeltaException(f'Invalid layer "{layer_id}"')

            if not layer.isEditable() and not layer.startEditing():
                raise DeltaException(
                    f'Cannot start editing layer "{layer_id}"',
                    provider_errors=layer.dataProvider().errors(),
                )

            has_edit_buffer = layer.editBuffer() and not isinstance(
                layer.editBuffer(), QgsVectorLayerEditPassthrough
            )
            delta = inverse_delta(delta) if inverse else delta

            if delta["method"] == str(DeltaMethod.CREATE):
                # don't use the returned feature as the PK might contain the "Autogenerated" string value, instead the real one
                created_feature = create_feature(
                    layer, delta, overwrite_conflicts=overwrite_conflicts
                )

                # apparently the only way to obtain the feature if there is no edit buffer is use the returned created_feature
                if not has_edit_buffer:
                    feature = created_feature
            elif delta["method"] == str(DeltaMethod.PATCH):
                feature = patch_feature(
                    layer,
                    delta,
                    overwrite_conflicts=overwrite_conflicts,
                    client_pks=delta_file.client_pks,
                )
            elif delta["method"] == str(DeltaMethod.DELETE):
                feature = delete_feature(
                    layer,
                    delta,
                    overwrite_conflicts=overwrite_conflicts,
                    client_pks=delta_file.client_pks,
                )
            else:
                raise DeltaException("Unknown delta method")

            def committed_features_added_cb(layer_id, features):
                if len(features) != 0 and len(features) != 1:
                    raise DeltaException(
                        f"Expected only one feature, but actually {len(features)} were added."
                    )

                if layer_id != layer.id():
                    raise DeltaException(
                        f"Expected the layer with the added layer to be {layer.id()}, but got {layer_id}."
                    )

                nonlocal feature
                feature = features[0]

            if has_edit_buffer:
                # in QGIS the only way to get the real features that have been added after commit, if edit buffer is present, is to use this signal.
                layer.committedFeaturesAdded.connect(committed_features_added_cb)

            if not layer.commitChanges():
                raise DeltaException(
                    "Failed to commit changes",
                    provider_errors=layer.dataProvider().errors(),
                )

            if has_edit_buffer:
                QCoreApplication.processEvents()
                layer.committedFeaturesAdded.disconnect(committed_features_added_cb)

            logger.info(f'Successfully applied delta on layer "{layer_id}"')

            feature_pk = delta.get("sourcePk")
            modified_pk = None
            if feature.isValid():
                _pk_attr_idx, pk_attr_name = find_layer_pk(layer)

                if not pk_attr_name:
                    raise DeltaException(f'Layer "{layer.name()}" has no primary key.')

                modified_pk = feature.attribute(pk_attr_name)

                if (
                    modified_pk is not None
                    # if the feature was newly created, do not expect `feature_pk` to match the `modified_pk`,
                    # as the client cannot know the modified_pk in advance.
                    and delta["method"] == str(DeltaMethod.CREATE)
                    and str(modified_pk) != str(feature_pk)
                ):
                    logger.warning(
                        f'The modified feature pk valued does not match "sourcePk" in the delta in "{layer_id}": sourcePk={feature_pk} modifiedFeaturePk={modified_pk}'
                    )
            else:
                logger.warning(
                    f'The returned modified feature is invalid in "{layer_id}"'
                )

            DELTA_LOG.append(
                {
                    "msg": "Successfully applied delta!",
                    "status": delta_status,
                    "e_type": None,
                    "delta_file_id": delta_file.id,
                    "layer_id": layer_id,
                    "delta_index": idx,
                    "delta_id": delta["uuid"],
                    "feature_pk": feature_pk,
                    "modified_pk": modified_pk,
                    "conflicts": None,
                    "provider_errors": None,
                    "method": delta["method"],
                }
            )

        except DeltaException as err:
            err.layer_id = err.layer_id or layer_id
            err.delta_file_id = err.delta_file_id or delta_file.id
            err.delta_idx = err.delta_idx or idx
            err.delta_id = err.delta_id or delta["uuid"]
            err.feature_pk = err.feature_pk or delta.get("sourcePk")
            err.method = err.method or delta.get("method")

            if err.e_type == DeltaExceptionType.Conflict:
                delta_status = DeltaStatus.Conflict
                logger.warning(f"Conflicts while applying a single delta: {err}")
            else:
                delta_status = DeltaStatus.ApplyFailed
                logger.warning(f"Error while applying a single delta: {err}")

            if layer is not None and not layer.rollBack():
                logger.error(f'Failed to rollback layer "{layer_id}": {err}')

            has_applied_all_deltas = False
            DELTA_LOG.append(
                {
                    "msg": str(err),
                    "status": delta_status,
                    "e_type": err.e_type,
                    "delta_file_id": err.delta_file_id,
                    "layer_id": err.layer_id,
                    "delta_index": err.delta_idx,
                    "delta_id": err.delta_id,
                    "feature_pk": err.feature_pk,
                    "modified_pk": err.modified_pk,
                    "conflicts": err.conflicts,
                    "provider_errors": err.provider_errors,
                    "method": err.method,
                }
            )
        except Exception as err:
            delta_status = DeltaStatus.UnknownError
            DELTA_LOG.append(
                {
                    "msg": str(err),
                    "status": delta_status,
                    "e_type": None,
                    "delta_file_id": delta_file.id,
                    "layer_id": layer_id,
                    "delta_index": idx,
                    "delta_id": delta.get("uuid"),
                    "feature_pk": None,
                    "modified_pk": None,
                    "conflicts": None,
                    "provider_errors": None,
                    "method": delta.get("method"),
                }
            )

            logger.error(
                f"An unknown error has been encountered while applying delta: {err}"
            )

            raise err

    return has_applied_all_deltas


def apply_deltas(
    project: QgsProject,
    delta_file: DeltaFile,
    inverse: bool = False,
    overwrite_conflicts: bool = False,
) -> DeltaStatus:
    """Applies the deltas from a loaded delta file on the layers in a project.

    The general algorithm is as follows:
    1) group all individual deltas by layer id.
    2) make a backup of the layer data source. In case things go wrong, one
    can rollback from them.
    3) apply deltas on each individual layer:
    startEditing -> apply changes -> commit
    4) if all is good, delete the backup files.

    Arguments:
        project {QgsProject} -- project
        delta_file {DeltaFile} -- delta file
        inverse {bool} -- inverses the direction of the deltas. Makes the
        delta `old` to `new` and `new` to `old`. Mainly used to rollback the
        applied changes using the same delta file.
        overwrite_conflicts {bool} -- whether the conflicts are ignored

    Returns:
        bool -- indicates whether a conflict occurred
    """
    has_conflict = False
    deltas_by_layer: Dict[LayerId, List[Delta]] = {}
    layers_by_id: Dict[LayerId, QgsVectorLayer] = {}
    transcation_by_layer: Dict[str, str] = {}
    opened_transactions: Dict[str, List[LayerId]] = {}

    for layer_id in project.mapLayers():
        layer = project.mapLayer(layer_id)
        conn_type = layer.providerType()
        conn_string = QgsDataSourceUri(layer.source()).connectionInfo(False)

        if len(conn_string) == 0:
            continue

        # here we use '$$$$$' as a separator, nothing special, can be easily changed to any other string
        transaction_id = conn_type + "$$$$$" + conn_string
        transcation_by_layer[layer_id] = transaction_id
        opened_transactions[transaction_id] = opened_transactions.get(
            transaction_id, []
        )
        opened_transactions[transaction_id].append(layer_id)

    # group all individual deltas by layer id
    for d in delta_file.deltas:
        layer_id = d["sourceLayerId"]
        deltas_by_layer[layer_id] = deltas_by_layer.get(layer_id, [])
        deltas_by_layer[layer_id].append(d)
        layers_by_id[layer_id] = project.mapLayer(layer_id)

        if not isinstance(layers_by_id[layer_id], QgsVectorLayer):
            raise DeltaException(
                "The layer does not exist: {}".format(layer_id), layer_id=layer_id
            )

    # make a backup of the layer data source.
    for layer_id in layers_by_id.keys():
        if not is_layer_file_based(layers_by_id[layer_id]):
            continue

        layer_path = get_layer_path(layers_by_id[layer_id])
        layer_backup_path = get_backup_path(layer_path)

        assert layer_path.exists()
        # TODO enable this when needed
        # assert not layer_backup_path.exists()

        if not shutil.copyfile(layer_path, layer_backup_path):
            raise DeltaException(
                "Unable to backup file for layer {}".format(layer_id),
                layer_id=layer_id,
                e_type=DeltaExceptionType.IO,
            )

    modified_layer_ids: Set[LayerId] = set()

    # apply deltas on each individual layer
    for layer_id in deltas_by_layer.keys():
        # keep the try/except block inside the loop, so we can have the `layer_id` context
        try:
            if apply_deltas_on_layer(
                layers_by_id[layer_id],
                deltas_by_layer[layer_id],
                inverse,
                overwrite_conflicts=overwrite_conflicts,
            ):
                has_conflict = True

            modified_layer_ids.add(layer_id)
        except DeltaException as err:
            rollback_deltas(layers_by_id)
            err.layer_id = err.layer_id or layer_id
            err.delta_file_id = err.delta_file_id or delta_file.id
            raise err
        except Exception as err:
            rollback_deltas(layers_by_id)
            raise DeltaException("Failed to apply changes") from err

    committed_layer_ids: Set[LayerId] = set()

    for layer_id in deltas_by_layer.keys():
        # keep the try/except block inside the loop, so we can have the `layer_id` context
        try:
            # the layer has already been commited. This might happend if there are multiple layers in the same transaction group.
            if layer_id in committed_layer_ids:
                continue

            if layers_by_id[layer_id].commitChanges():
                transaction_id = transcation_by_layer.get(layer_id)

                if transaction_id and transaction_id in opened_transactions:
                    committed_layer_ids = set(
                        [*committed_layer_ids, *opened_transactions[transaction_id]]
                    )
                    del opened_transactions[transaction_id]
                else:
                    committed_layer_ids.add(layer_id)
            else:
                raise DeltaException("Failed to commit")
        except DeltaException:
            # all the modified layers must be rollbacked
            for layer_id in modified_layer_ids - committed_layer_ids:
                if not layers_by_id[layer_id].rollBack():
                    logger.warning("Failed to rollback")

            rollback_deltas(layers_by_id, committed_layer_ids=committed_layer_ids)

    if not cleanup_backups(set(layers_by_id.keys())):
        logger.warning("Failed to cleanup backups, other than that - success")

    return DeltaStatus.Conflict if has_conflict else DeltaStatus.Applied


def rollback_deltas(
    layers_by_id: Dict[LayerId, QgsVectorLayer],
    committed_layer_ids: Set[LayerId] = set(),
) -> bool:
    """Rollback applied deltas by restoring the layer data source backup files.

    Arguments:
        layers_by_id {Dict[LayerId, QgsVectorLayer]} -- layers
        committed_layer_ids {Set[LayerId]} -- layer ids to be rollbacked.

    Returns:
        bool -- whether there were no rollback errors. If True, the state of
        the project might be broken, but the old data is preserved in the
        backup files.
    """
    is_success = True
    # we need to keep the backups of `committed_layer_ids` in case something goes wrong
    backups_to_remove_layer_ids = set(layers_by_id.keys()) - committed_layer_ids

    # first rollback the buffer of each layer
    for layer in layers_by_id.values():
        if layer.isEditable():
            if layer.rollBack():
                logger.warning("Unable to rollback layer {}".format(layer.id()))

    # if there are already committed layers, restore the backup
    for layer_id in committed_layer_ids:
        if not layers_by_id.get(layer_id):
            logger.warning(
                "Unable to restore original layer file, path missing: {}".format(
                    layer_id
                )
            )
            continue

        layer_path = get_layer_path(layers_by_id[layer_id])
        layer_backup_path = get_backup_path(layer_path)

        # NOTE pathlib operations will raise in case of error
        try:
            layer_backup_path.rename(layer_path)
        except Exception as err:
            # TODO nothing better to do here?
            is_success = False
            logger.warning(
                "Unable to restore original layer file: {}. Reason: {}".format(
                    layer_id, err
                )
            )

    # no mater what, try to cleanup the backups that are no longer needed.
    # this way it would be easier to restore the original state.
    cleanup_backups(backups_to_remove_layer_ids)

    return is_success


def cleanup_backups(layer_paths: Set[str]) -> bool:
    """Cleanup the layer backups. Attempts to remove all backup files, whether
    or not there is an error.

    Arguments:
        layer_paths {Set[str]} -- layer paths, which should have their
        backups removed

    Returns:
        bool -- whether all paths are successfully removed.
    """
    is_success = True

    for layer_path in layer_paths:
        layer_path = Path(layer_path)
        layer_backup_path = get_backup_path(layer_path)
        try:
            if layer_backup_path.exists():
                layer_backup_path.unlink()
        except Exception as err:
            is_success = False
            logger.warning(
                "Unable to remove backup: {}. Reason: {}".format(layer_backup_path, err)
            )

    return is_success


def apply_deltas_on_layer(
    layer: QgsVectorLayer,
    deltas: List[Delta],
    inverse: bool,
    should_commit: bool = False,
    overwrite_conflicts: bool = False,
) -> bool:
    """Applies the deltas on the layer provided.

    Arguments:
        layer {QgsVectorLayer} -- target layer
        deltas {List[Delta]} -- ordered list of deltas to be applied
        inverse {bool} -- inverses the direction of the deltas. Makes the
        delta `old` to `new` and `new` to `old`. Mainly used to rollback the
        applied changes using the same delta file.

    Keyword Arguments:
        should_commit {bool} -- whether the changes should be committed
        (default: {False})
        overwrite_conflicts {bool} -- whether the conflicts are ignored

    Raises:
        DeltaException: whenever the changes cannot be applied

    Returns:
        bool -- indicates whether a conflict occurred
    """
    assert layer is not None
    assert layer.type() == QgsMapLayerType.VectorLayer

    has_conflict = False

    if not layer.isEditable() and not layer.startEditing():
        raise DeltaException("Cannot start editing")

    for idx, d in enumerate(deltas):
        assert d["sourceLayerId"] == layer.id()

        delta = inverse_delta(d) if inverse else d

        try:
            if delta["method"] == str(DeltaMethod.CREATE):
                create_feature(layer, delta, overwrite_conflicts=overwrite_conflicts)
            elif delta["method"] == str(DeltaMethod.PATCH):
                patch_feature(layer, delta, overwrite_conflicts=overwrite_conflicts)
            elif delta["method"] == str(DeltaMethod.DELETE):
                delete_feature(layer, delta, overwrite_conflicts=overwrite_conflicts)
            else:
                raise DeltaException("Unknown delta method")
        except DeltaException as err:
            # TODO I am lazy now and all these properties are set only here, but should be moved in depth
            err.layer_id = err.layer_id or layer.id()
            err.delta_idx = err.delta_idx or idx
            err.delta_id = err.delta_id or delta.get("id")
            err.method = err.method or delta.get("method")
            err.feature_pk = err.feature_pk or delta.get("sourcePk")
            err.provider_errors = err.provider_errors or layer.dataProvider().errors()

            if err.e_type == DeltaExceptionType.Conflict:
                has_conflict = True
                logger.warning(
                    "Conflicts while applying a single delta: {}".format(str(err)), err
                )
            else:
                if not layer.rollBack():
                    # So unfortunate situation, that the only safe thing to do is to cancel the whole script
                    raise DeltaException(
                        "Cannot rollback layer changes: {}".format(layer.id())
                    ) from err

                raise err
        except Exception as err:
            if not layer.rollBack():
                # So unfortunate situation, that the only safe thing to do is to cancel the whole script
                raise DeltaException(
                    "Cannot rollback layer changes: {}".format(layer.id())
                ) from err

            raise DeltaException(
                "An error has been encountered while applying delta:"
                + str(err).replace("\n", ""),
                layer_id=layer.id(),
                delta_idx=idx,
                delta_id=delta.get("id"),
                method=delta.get("method"),
                descr=traceback.format_exc(),
                feature_pk=delta.get("sourcePk"),
            ) from err

    if should_commit and not layer.commitChanges():
        if not layer.rollBack():
            # So unfortunate situation, that the only safe thing to do is to cancel the whole script
            raise DeltaException("Cannot rollback layer changes: {}".format(layer.id()))

        raise DeltaException("Cannot commit changes")

    return has_conflict


def find_layer_pk(layer: QgsVectorLayer) -> Tuple[int, str]:
    fields = layer.fields()
    pk_attrs = [*layer.primaryKeyAttributes(), fields.indexFromName("fid")]
    # we assume the first index to be the primary key index... kinda stupid, but memory layers don't have primary key at all, but we use it on geopackages, but... snap!
    pk_attr_idx = pk_attrs[0]

    if pk_attr_idx == -1:
        return (-1, "")

    pk_attr_name = fields.at(pk_attr_idx).name()

    return (pk_attr_idx, pk_attr_name)


def get_feature(
    layer: QgsVectorLayer, delta: Delta, client_pks: Dict[str, str] = None
) -> QgsFeature:
    _pk_attr_idx, pk_attr_name = find_layer_pk(layer)

    assert pk_attr_name

    source_pk = delta["sourcePk"]

    if client_pks:
        client_pk_key = f'{delta["clientId"]}__{delta["localPk"]}'
        if client_pk_key in client_pks:
            source_pk = client_pks[client_pk_key]

    expr = " {} = {} ".format(
        QgsExpression.quotedColumnRef(pk_attr_name),
        QgsExpression.quotedValue(source_pk),
    )

    features = list(layer.getFeatures(expr))
    if not features:
        raise FeatureNotFoundError(f"Could not find feature source_pk={source_pk}")
    if len(features) < 1:
        raise DoublicateFeatureError(
            f"More than one feature match the feature select query source_pk={source_pk}"
        )
    return features[0]


def create_feature(
    layer: QgsVectorLayer, delta: Delta, overwrite_conflicts: bool
) -> QgsFeature:
    """Creates new feature in layer

    Arguments:
        layer {QgsVectorLayer} -- target layer. Must be in editing mode!
        delta {Delta} -- delta describing the created feature
        overwrite_conflicts {bool} -- if there are conflicts with an existing feature, ignore them

    Raises:
        DeltaException: whenever the feature cannot be created
    """
    fields = layer.fields()
    new_feat_delta = delta["new"]
    geometry = get_geometry_from_delta(new_feat_delta, layer)

    # NOTE Make sure the geometry is a `QgsGeometry` instance, even though invalid, as `QgsVectorLayerUtils.createFeature()` requires it. Might be `None` if the layer is not spatial.
    if geometry is None:
        if layer.isSpatial():
            logger.warning("A spatial layer delta should always contain a geometry.")

        geometry = QgsGeometry()

    new_feat_attrs = new_feat_delta.get("attributes", {})
    feat_attrs = {}

    if new_feat_attrs:
        # `fid` is an extra field created during conversion to gpkg and makes this assert to fail.
        # if fields.size() < len(new_feat_attrs):
        #     raise DeltaException('The layer has less attributes than the provided by the delta')

        if new_feat_attrs:
            for field in fields:
                attr_name = field.name()

                if attr_name in new_feat_attrs:
                    attr_value = new_feat_attrs[attr_name]
                    attr_index = fields.indexFromName(attr_name)
                    feat_attrs[attr_index] = attr_value

    new_feat = QgsVectorLayerUtils.createFeature(layer, geometry, feat_attrs)

    if not new_feat.isValid():
        raise DeltaException("Unable to create a valid feature")

    if not layer.addFeature(new_feat):
        raise DeltaException(
            "Unable to add new feature", provider_errors=layer.dataProvider().errors()
        )

    return new_feat


def patch_feature(
    layer: QgsVectorLayer,
    delta: Delta,
    overwrite_conflicts: bool,
    client_pks: Dict[str, str],
) -> QgsFeature:
    """Patches a feature in layer

    Arguments:
        layer {QgsVectorLayer} -- target layer. Must be in edit mode!
        delta {Delta} -- delta describing the patch
        overwrite_conflicts {bool} -- if there are conflicts with an existing feature, ignore them

    Raises:
        DeltaException: whenever the feature cannot be patched
    """
    new_feature_delta = delta["new"]
    old_feature_delta = delta["old"]
    try:
        old_feature = get_feature(layer, delta, client_pks)
    except (FeatureNotFoundError, DoublicateFeatureError) as exc:
        raise DeltaException("Could not get feature", method=delta["method"]) from exc

    conflicts = compare_feature(old_feature, old_feature_delta, True)

    if len(conflicts) != 0:
        if overwrite_conflicts:
            logger.warning(
                f'Conflicts while applying delta "{delta["uuid"]}". Ignoring since `overwrite_conflicts` flag set to `True`.\nConflicts:\n{conflicts}'
            )
        else:
            raise DeltaException(
                "There are conflicts with the already existing feature!",
                conflicts=conflicts,
                e_type=DeltaExceptionType.Conflict,
            )

    geometry = None

    if "geometry" in new_feature_delta:
        if layer.isSpatial():
            if new_feature_delta["geometry"] == old_feature_delta.get("geometry"):
                logger.warning(
                    "The geometries of the new and the old features are the same, even though by spec they should not be provided in such case. Ignoring geometry."
                )
            else:
                geometry = get_geometry_from_delta(new_feature_delta, layer)

                # NOTE if the geometry is `None`, it means the geometry has not been modified.
                if geometry is not None:
                    if not layer.changeGeometry(old_feature.id(), geometry, True):
                        raise DeltaException(
                            "Unable to change geometry",
                            provider_errors=layer.dataProvider().errors(),
                        )
        else:
            logger.warning("Layer is not spatial, ignoring geometry")

    fields = layer.fields()
    new_attrs = new_feature_delta.get("attributes") or {}
    old_attrs = old_feature_delta.get("attributes") or {}

    for attr_name, new_attr_value in new_attrs.items():
        # NOTE the old_attrs may be missing or empty
        old_attr_value = old_attrs.get(attr_name)

        if new_attrs[attr_name] == old_attr_value:
            logger.warning(
                "The delta has features with the same value in both old and new values"
            )
            continue

        if not layer.changeAttributeValue(
            old_feature.id(),
            fields.indexOf(attr_name),
            new_attr_value,
            old_attrs[attr_name],
            True,
        ):
            raise DeltaException(
                'Unable to change attribute "{}"'.format(attr_name),
                provider_errors=layer.dataProvider().errors(),
            )

    return layer.getFeature(old_feature.id())


def delete_feature(
    layer: QgsVectorLayer,
    delta: Delta,
    overwrite_conflicts: bool,
    client_pks: Dict[str, str],
) -> QgsFeature:
    """Deletes a feature from layer

    Arguments:
        layer {QgsVectorLayer} -- target layer. Must be in edit mode!
        delta {Delta} -- delta describing the deleted feature
        overwrite_conflicts {bool} -- if there are conflicts with an existing feature, ignore them

    Raises:
        DeltaException: whenever the feature cannot be deleted
    """
    old_feature_delta = delta["old"]
    try:
        old_feature = get_feature(layer, delta, client_pks)
    except (FeatureNotFoundError, DoublicateFeatureError) as exc:
        raise DeltaException("Could not get feature", method=delta["method"]) from exc

    conflicts = compare_feature(old_feature, old_feature_delta)

    if len(conflicts) != 0:
        if overwrite_conflicts:
            logger.warning(
                f'Conflicts while applying delta "{delta["uuid"]}". Ignoring since `overwrite_conflicts` flag set to `True`.\nConflicts:\n{conflicts}'
            )
        else:
            logger.warning(
                f'Conflicts while applying delta "{delta["uuid"]}".\nConflicts:\n{conflicts}'
            )
            raise DeltaException(
                "There are conflicts with the already existing feature!",
                conflicts=conflicts,
                e_type=DeltaExceptionType.Conflict,
            )

    if not layer.deleteFeature(old_feature.id()):
        raise DeltaException("Unable delete feature")

    return old_feature


def compare_feature(
    feature: QgsFeature, delta_feature: DeltaFeature, is_delta_subset: bool = False
) -> List[str]:
    """Compares a feature with delta description of a feature and reports the
    differences. Checks both the geometry and the attributes. If
    {is_delta_subset} is true, allows the delta attributes to be subset of the
    {feature} attributes.

    Arguments:
        feature {QgsFeature} -- target feature
        delta_feature {DeltaFeature} -- target delta description of a feature

    Keyword Arguments:
        is_delta_subset {bool} -- whether to precisely match the delta attributes
        on the original feature (default: {False})

    Returns:
        List[str] -- a list of differences found
    """
    # NOTE this can be something more structured, JSON like object.
    # However, I think we should not record the diff/conflicts, as they may change if the underlying feature is updated.
    conflicts: List[str] = []

    # TODO enable once we are done
    # if delta_feature.get('geometry') != feature.geometry().asWkt(17):
    #     conflicts.append('Geometry missmatch')

    delta_feature_attrs: Optional[Dict[str, Any]] = delta_feature.get("attributes")

    if delta_feature_attrs:
        delta_feature_attr_names = delta_feature_attrs.keys()
        feature_attr_names = feature.fields().names()

        # TODO reenable this, when it is clear what we do when there is property mismatch
        # if not is_delta_subset:
        #     for attr in feature_attr_names:
        #         if attr not in delta_feature_attr_names:
        #             conflicts.append(f'The attribute "{attr}" in the original feature is not available in the delta')

        for attr in delta_feature_attr_names:
            if attr not in feature_attr_names:
                # TODO reenable this, when it is clear what we do when there is property mismatch
                # conflicts.append(f'The attribute "{attr}" in the delta is not available in the original feature')
                continue

            current_value = feature.attribute(attr)
            incoming_value = delta_feature_attrs[attr]

            # modify the incoming value to the desired type if needed
            if incoming_value is not None:
                if isinstance(current_value, QDateTime):
                    incoming_value = QDateTime.fromString(
                        incoming_value, Qt.ISODateWithMs
                    )
                elif isinstance(current_value, QDate):
                    incoming_value = QDate.fromString(incoming_value, Qt.ISODate)
                elif isinstance(current_value, QTime):
                    incoming_value = QTime.fromString(incoming_value)

            if current_value != incoming_value:
                conflicts.append(
                    f'The attribute "{attr}" that has a conflict:\n-{current_value}\n+{incoming_value}'
                )

    return conflicts


@lru_cache(maxsize=128)
def get_layer_path(layer: QgsMapLayer) -> Path:
    """Returns a `Path` object of the data source filename of the given layer.

    Arguments:
        layer {QgsMapLayer} -- target layer

    Returns:
        Path -- `Path` object
    """
    data_source_uri = layer.dataProvider().dataSourceUri()
    data_source_decoded = QgsProviderRegistry.instance().decodeUri(
        "ogr", data_source_uri
    )
    return Path(data_source_decoded["path"])


def get_backup_path(path: Path) -> Path:
    """Returns a `Path` object of with backup suffix

    Arguments:
        path {Path} -- target path

    Returns:
        Path -- suffixed path
    """
    return path.with_suffix(BACKUP_SUFFIX)


def is_layer_file_based(layer: QgsMapLayer) -> bool:
    return len(str(get_layer_path(layer))) == 0


def inverse_delta(delta: Delta) -> Delta:
    """Returns shallow copy of the delta with reversed `old` and `new` keys

    Arguments:
        delta {Delta} -- delta

    Returns:
        [type] -- reversed delta
    """
    copy: Dict[str, Any] = {**delta}
    copy["old"], copy["new"] = delta.get("new"), delta.get("old")

    if copy["method"] == DeltaMethod.CREATE.name:
        copy["method"] = DeltaMethod.DELETE.name
    elif copy["method"] == DeltaMethod.DELETE.name:
        copy["method"] = DeltaMethod.CREATE.name

    return cast(Delta, copy)


if __name__ == "__main__":
    from qfieldcloud.qgis.utils import setup_basic_logging_config

    setup_basic_logging_config()

    parser = argparse.ArgumentParser(
        prog="COMMAND",
        description="",
        formatter_class=argparse.RawDescriptionHelpFormatter,  # type: ignore
        epilog=textwrap.dedent(
            """
            example:
                # apply deltas on a project
                ./apply_delta.py delta apply ./path/to/project.qgs ./path/to/delta.json

                # rollback deltas on a project
                ./apply_delta.py delta apply --inverse ./path/to/project.qgs ./path/to/delta.json

                # rollback deltas on a project
                ./apply_delta.py backup cleanup
        """
        ),
    )
    parser.add_argument(
        "--skip-csv-header",
        action="store_true",
        help="Skip writing CSV header in the log file",
    )

    subparsers = parser.add_subparsers(dest="cmd0")

    # deltas
    parser_delta = subparsers.add_parser(
        "delta", help="rollback a delta file on a project"
    )
    delta_subparsers = parser_delta.add_subparsers(dest="cmd1")

    parser_delta_apply = delta_subparsers.add_parser(
        "apply", help="apply a delta file on a project"
    )
    parser_delta_apply.add_argument("project", type=str, help="Path to QGIS project")
    parser_delta_apply.add_argument("delta_file", type=str, help="Path to delta file")
    parser_delta_apply.add_argument(
        "--delta-log", type=str, help="Path to delta log file"
    )
    parser_delta_apply.add_argument(
        "--overwrite-conflicts",
        action="store_true",
        help="Apply deltas even if there are conflicts.",
    )
    parser_delta_apply.add_argument(
        "--inverse",
        action="store_true",
        help="Inverses the direction of the deltas. Makes the delta `old` to `new` and `new` to `old`. Mainly used to rollback the applied changes using the same delta file..",
    )
    parser_delta_apply.add_argument(
        "--transaction",
        action="store_true",
        help='Apply individual deltas in the deltafile in the "all-or-nothing" manner, with transaction mode enabled',
    )
    parser_delta_apply.set_defaults(func=cmd_delta_apply)
    # /deltas

    # backup
    parser_backup = subparsers.add_parser(
        "backup", help="rollback a delta file on a project"
    )
    backup_subparsers = parser_backup.add_subparsers(dest="cmd1")

    parser_backup_cleanup = backup_subparsers.add_parser(
        "cleanup", help="rollback a delta file on a project"
    )
    parser_backup_cleanup.add_argument("project", type=str, help="Path to QGIS project")
    parser_backup_cleanup.add_argument(
        "--transaction",
        action="store_true",
        help='Apply individual deltas in the deltafile in the "all-or-nothing" manner, with transaction mode enabled',
    )
    parser_backup_cleanup.set_defaults(func=cmd_backup_cleanup)

    parser_backup_rollback = backup_subparsers.add_parser(
        "rollback", help="rollback a delta file on a project"
    )
    parser_backup_rollback.add_argument(
        "project", type=str, help="Path to QGIS project"
    )
    parser_backup_rollback.add_argument(
        "--transaction",
        action="store_true",
        help='Apply individual deltas in the deltafile in the "all-or-nothing" manner, with transaction mode enabled',
    )
    parser_backup_rollback.set_defaults(func=cmd_backup_rollback)
    # /backup

    args = parser.parse_args()

    if "func" in args:
        args.func(vars(args))  # type: ignore
    else:
        parser.parse_args(["-h"])
