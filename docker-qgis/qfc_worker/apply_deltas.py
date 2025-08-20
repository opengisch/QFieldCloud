#!/usr/bin/env python3

import re
from enum import Enum
from typing import Any, Callable, cast

try:
    # 3.8
    from typing import TypedDict
except ImportError:
    # 3.7
    from typing_extensions import TypedDict

import argparse
import json
import logging
import textwrap
import traceback
from functools import lru_cache
from pathlib import Path

import jsonschema

# pylint: disable=no-name-in-module
from qgis.core import (
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
    delta_file: str | None
    delta_contents: dict | None
    delta_log: str | None
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
    geometry: WKT | None
    attributes: dict[str, Any] | None
    file_sha256: dict[str, str] | None


class Delta(TypedDict):
    uuid: Uuid
    clientId: Uuid
    localPk: FeaturePk
    sourcePk: FeaturePk
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
        deltas: list[dict | Delta],
        files: list[str],
        client_pks: dict[str, str],
    ):
        self.id = delta_file_id
        self.project_id = project_id
        self.version = version
        self.files = files
        self.client_pks = client_pks
        self.deltas: list[Delta] = []

        for d in deltas:
            self.deltas.append(cast(Delta, d))


# /TYPE DEFINITIONS


# EXCEPTION DEFINITIONS\
class DeltaException(Exception):
    def __init__(
        self,
        msg: str,
        e_type: DeltaExceptionType = DeltaExceptionType.Error,
        delta_file_id: str | None = None,
        layer_id: str | None = None,
        delta_idx: int | None = None,
        delta_id: str | None = None,
        feature_pk: str | None = None,
        modified_pk: str | None = None,
        conflicts: list[str] | None = None,
        method: DeltaMethod | None = None,
        provider_errors: str | None = None,
        descr: str | None = None,
    ):
        super().__init__(msg)
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


# /EXCEPTION DEFINITIONS


BACKUP_SUFFIX = ".qfieldcloudbackup"
delta_log = []


def project_decorator(f):
    def wrapper(opts: DeltaOptions, *args, **kw):
        project = QgsProject.instance()
        project.setAutoTransaction(opts["transaction"])
        project.read(opts.get("the_qgis_file_name", opts["project"]))

        return f(project, opts, *args, **kw)  # type: ignore

    return wrapper


def wkt_nan_to_zero(wkt: WKT) -> WKT:
    """Support of `nan` values is non-standard in WKT.

    Since it is poorly supported on QGIS and other FOSS tools, it's safer to convert the `nan` values to 0s for now. See https://github.com/qgis/QGIS/pull/47034/ .

    Args:
        wkt: wkt that might contain `nan` values

    Returns:
        WKT with `nan` values replaced with `0`s
    """
    old_wkt = wkt
    new_wkt = re.sub(r"\bnan\b", "0", wkt, flags=re.IGNORECASE)

    if old_wkt != new_wkt:
        logger.info(f"Replaced nan values with 0s for {wkt=}")

    return new_wkt


def get_geometry_from_delta(
    delta_feature: DeltaFeature, layer: QgsVectorLayer
) -> QgsGeometry | None:
    """Converts the `geometry` WKT from the `DeltaFeature` to a `QgsGeometry` instance.

    Args:
        delta_feature: delta feature
        layer: layer the feature is part of

    Raises:
        DeltaException

    Returns:
        the parsed `QgsGeometry`. Might be invalid geometry. Returns `None` if no geometry has been modified.
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
    the_qgis_file_name: Path,
    delta_filename: Path,
    inverse: bool,
    overwrite_conflicts: bool,
):
    del delta_log[:]

    project = QgsProject.instance()
    logging.info(f'Loading project file "{the_qgis_file_name}"...')
    project.read(str(the_qgis_file_name))

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

    delta_log_copy = [*delta_log]
    del delta_log[:]

    return delta_log_copy


@project_decorator
def cmd_delta_apply(project: QgsProject, opts: DeltaOptions) -> bool:
    accepted_state = None
    deltas = None
    has_uncaught_errors = False

    try:
        del delta_log[:]
        deltas = load_delta_file(opts)
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
    print(json.dumps(delta_log, indent=2, sort_keys=True, default=str))
    print("========================")

    if opts.get("delta_log"):
        with open(str(opts["delta_log"]), "w") as f:
            json.dump(delta_log, f, indent=2, sort_keys=True, default=str)

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


def delta_file_args_loader(args: DeltaOptions) -> DeltaFile | None:
    """Get delta file contents as a dictionary passed in the args. Mostly used for testing.

    Args:
        args: main options

    Returns:
        loaded delta file on success, otherwise none
    """
    obj = args.get("delta_contents")
    if not obj:
        return None

    obj = cast(dict, obj)

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


def delta_file_file_loader(args: DeltaOptions) -> DeltaFile | None:
    """Get delta file contents from a filesystem file.

    Args:
        args: main options

    Returns:
        loaded delta file on success, otherwise none
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

    Args:
        args: main options

    Returns:
        the loaded deltafile
    """
    deltas: DeltaFile | None = None

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
        layer_id: str = delta.get("sourceLayerId", "")
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

            pk_attr_name = get_pk_attr_name(layer)
            if not pk_attr_name:
                raise DeltaException(f'Layer "{layer.name()}" has no primary key.')

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

            logger.info(
                f'Successfully applied delta "{delta.get("uuid")}" on layer "{layer_id}"!'
            )

            feature_pk = delta.get("sourcePk")
            modified_pk = None
            if feature.isValid():
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

            delta_log.append(
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
            delta_log.append(
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
            delta_log.append(
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


def rollback_deltas(
    layers_by_id: dict[LayerId, QgsVectorLayer],
    committed_layer_ids: set[LayerId] = set(),
) -> bool:
    """Rollback applied deltas by restoring the layer data source backup files.

    Args:
        layers_by_id: layers
        committed_layer_ids: layer ids to be rollbacked.

    Returns:
        whether there were no rollback errors. If True, the state of
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
                logger.warning(f"Unable to rollback layer {layer.id()}")

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


def cleanup_backups(layer_paths: set[str]) -> bool:
    """Cleanup the layer backups. Attempts to remove all backup files, whether
    or not there is an error.

    Args:
        layer_paths: layer paths, which should have their backups removed

    Returns:
        whether all paths are successfully removed.
    """
    is_success = True

    for layer_path_str in layer_paths:
        layer_path = Path(layer_path_str)
        layer_backup_path = get_backup_path(layer_path)
        try:
            if layer_backup_path.exists():
                layer_backup_path.unlink()
        except Exception as err:
            is_success = False
            logger.warning(
                f"Unable to remove backup: {layer_backup_path}. Reason: {err}"
            )

    return is_success


# NOTE this is very similar to the implementation in `libqfieldsync`.
# I preferred to copy-paste it, rather than adding `libqfieldsync` as a dependency on the `apply_deltas`.
@lru_cache()
def get_pk_attr_name(layer: QgsVectorLayer) -> str:
    pk_attr_name: str = ""

    if layer.type() != QgsMapLayer.VectorLayer:
        raise DeltaException(f"Expected layer {layer.name()} to be a vector layer!")

    pk_indexes = layer.primaryKeyAttributes()
    fields = layer.fields()

    if len(pk_indexes) == 1:
        pk_attr_name = fields[pk_indexes[0]].name()
    elif len(pk_indexes) > 1:
        raise DeltaException("Composite (multi-column) primary keys are not supported!")
    else:
        logger.info(
            f'Layer "{layer.name()}" does not have a primary key. Trying to fallback to `fid`…'
        )

        # NOTE `QgsFields.lookupField(str)` is case insensitive (so we support "fid", "FID", "Fid" etc),
        # but also looks for the field alias, that's why we check the `field.name().lower() == "fid"`
        fid_idx = fields.lookupField("fid")
        if fid_idx >= 0 and fields.at(fid_idx).name().lower() == "fid":
            fid_name = fields.at(fid_idx).name()
            logger.info(
                f'Layer "{layer.name()}" does not have a primary key so it uses the `fid` attribute as a fallback primary key. '
                "This is an unstable feature! "
                "Consider [converting to GeoPackages instead](https://docs.qfield.org/get-started/tutorials/get-started-qfc/#configure-your-project-layers-for-qfield). "
            )
            pk_attr_name = fid_name

    if not pk_attr_name:
        raise DeltaException(
            f'Layer "{layer.name()}" neither has a primary key, nor an attribute `fid`! '
        )

    if "," in pk_attr_name:
        raise DeltaException(f'Comma in field name "{pk_attr_name}" is not allowed!')

    logger.info(
        f'Layer "{layer.name()}" will use attribute "{pk_attr_name}" as a primary key.'
    )

    return pk_attr_name


def get_feature(
    layer: QgsVectorLayer, delta: Delta, client_pks: dict[str, str] | None = None
) -> QgsFeature:
    pk_attr_name = get_pk_attr_name(layer)

    assert pk_attr_name

    source_pk = delta["sourcePk"]

    if client_pks:
        client_pk_key = (
            f"{delta['clientId']}__{delta['localLayerId']}__{delta['localPk']}"
        )
        if client_pk_key in client_pks:
            source_pk = client_pks[client_pk_key]

    expr = " {} = {} ".format(
        QgsExpression.quotedColumnRef(pk_attr_name),
        QgsExpression.quotedValue(source_pk),
    )

    feature = QgsFeature()
    has_feature = False
    for f in layer.getFeatures(expr):
        if has_feature:
            raise Exception("More than one feature match the feature select query")

        feature = f
        has_feature = True

    return feature


def create_feature(
    layer: QgsVectorLayer, delta: Delta, overwrite_conflicts: bool
) -> QgsFeature:
    """Creates new feature in layer

    Args:
        layer: target layer. Must be in editing mode!
        delta: delta describing the created feature
        overwrite_conflicts: if there are conflicts with an existing feature, ignore them

    Raises:
        DeltaException: whenever the feature cannot be created

    Returns:
        The created QGIS feature.
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
    client_pks: dict[str, str],
) -> QgsFeature:
    """Patches a feature in layer

    Args:
        layer: target layer. Must be in edit mode!
        delta: delta describing the patch
        overwrite_conflicts: if there are conflicts with an existing feature, ignore them

    Raises:
        DeltaException: whenever the feature cannot be patched

    Returns:
        The patched QGIS feature.
    """
    new_feature_delta = delta["new"]
    old_feature_delta = delta["old"]
    old_feature = get_feature(layer, delta, client_pks)

    if not old_feature.isValid():
        raise DeltaException("Unable to find feature")

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
                f'Unable to change attribute "{attr_name}"',
                provider_errors=layer.dataProvider().errors(),
            )

    return layer.getFeature(old_feature.id())


def delete_feature(
    layer: QgsVectorLayer,
    delta: Delta,
    overwrite_conflicts: bool,
    client_pks: dict[str, str],
) -> QgsFeature:
    """Deletes a feature from layer

    Args:
        layer: target layer. Must be in edit mode!
        delta: delta describing the deleted feature
        overwrite_conflicts: if there are conflicts with an existing feature, ignore them

    Raises:
        DeltaException: whenever the feature cannot be deleted

    Returns:
        The deleted QGIS feature.
    """
    old_feature_delta = delta["old"]
    old_feature = get_feature(layer, delta, client_pks)

    if not old_feature.isValid():
        raise DeltaException("Unable to find feature")

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
) -> list[str]:
    """Compares a feature with delta description of a feature and reports the
    differences. Checks both the geometry and the attributes. If
    {is_delta_subset} is true, allows the delta attributes to be subset of the
    {feature} attributes.

    Args:
        feature: target feature
        delta_feature: target delta description of a feature
        is_delta_subset: whether to precisely match the delta attributes
        on the original feature (default: {False})

    Returns:
        A list of differences found.
    """
    # NOTE this can be something more structured, JSON like object.
    # However, I think we should not record the diff/conflicts, as they may change if the underlying feature is updated.
    conflicts: list[str] = []

    # TODO enable once we are done
    # if delta_feature.get('geometry') != feature.geometry().asWkt(17):
    #     conflicts.append('Geometry missmatch')

    delta_feature_attrs: dict[str, Any] | None = delta_feature.get("attributes")

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

    Args:
        layer: target layer

    Returns:
        Layer's path
    """
    data_source_uri = layer.dataProvider().dataSourceUri()
    data_source_decoded = QgsProviderRegistry.instance().decodeUri(
        "ogr", data_source_uri
    )
    return Path(data_source_decoded["path"])


def get_backup_path(path: Path) -> Path:
    """Returns a `Path` object of with backup suffix

    Args:
        path: target path

    Returns:
        Layer's backup path
    """
    return Path(str(path) + BACKUP_SUFFIX)


def is_layer_file_based(layer: QgsMapLayer) -> bool:
    return len(str(get_layer_path(layer))) == 0


def inverse_delta(delta: Delta) -> Delta:
    """Returns shallow copy of the delta with reversed `old` and `new` keys

    Args:
        delta: delta

    Returns:
        reversed delta
    """
    copy: dict[str, Any] = {**delta}
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
