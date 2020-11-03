#!/usr/bin/env python3

from typing import (Tuple, cast, Optional, List, Dict, Union, Set, Any, Callable)
from enum import Enum

try:
    # 3.8
    from typing import TypedDict
except ImportError:
    # 3.7
    from typing_extensions import TypedDict


from pathlib import Path
from functools import lru_cache
import shutil
import json
import argparse
import textwrap
from datetime import datetime
import logging
import csv
import io
import traceback

import jsonschema


# pylint: disable=no-name-in-module
from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsMapLayerType,
    QgsFeature,
    QgsGeometry,
    QgsExpression,
    QgsDataSourceUri,
    QgsProviderRegistry)
from qgis.testing import start_app


# LOGGER
class CsvFormatter(logging.Formatter):
    def __init__(self, skip_csv_header: bool = False):
        super().__init__()
        self.output = io.StringIO()
        self.fieldnames = ['asctime', 'elapsed', 'level', 'message', 'filename', 'lineno', 'e_type', 'delta_file_id', 'layer_id', 'delta_index', 'delta_id', 'feature_pk', 'attribute', 'conflict', 'exception', 'method']
        self.writer = csv.DictWriter(self.output, fieldnames=self.fieldnames, quoting=csv.QUOTE_NONNUMERIC)

        if not skip_csv_header:
            self.writer.writeheader()

    def format(self, record: logging.LogRecord) -> str:
        exception: Optional[Exception] = None
        log_string = ''
        log_data = {
            'asctime': datetime.fromtimestamp(record.created).isoformat(),
            'elapsed': record.relativeCreated,
            'level': record.levelname,
            'message': record.msg,
            'lineno': record.lineno,
            'filename': record.filename,
        }

        if isinstance(record.args, tuple) and len(record.args) >= 1 and isinstance(record.args[-1], Exception):
            exception = record.args[-1]

        if exception:
            if isinstance(exception, DeltaException):
                conflicts = exception.conflicts if exception.conflicts else [None]

                for conflict in conflicts:
                    self.writer.writerow({
                        **log_data,
                        'level': record.levelname,
                        'e_type': exception.e_type,
                        'delta_file_id': exception.delta_file_id,
                        'layer_id': exception.layer_id,
                        'delta_index': exception.delta_idx,
                        'feature_pk': exception.feature_pk,
                        'attribute': exception.attr,
                        'conflict': conflict,
                        'exception': exception.descr,
                        'method': exception.method})
            else:
                self.writer.writerow({
                    **log_data,
                    'e_type': DeltaExceptionType.Error})
        else:
            self.writer.writerow(log_data)

        log_string = self.output.getvalue()

        self.output.truncate(0)
        self.output.seek(0)

        return log_string.strip()


logging.basicConfig(level=logging.DEBUG)

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
    inverse: bool


class DeltaMethod(Enum):
    CREATE = 'create'
    PATCH = 'patch'
    DELETE = 'delete'


class DeltaExceptionType(Enum):
    def __str__(self):
        return str(self.value)

    Error = 'ERROR'
    IO = 'IO'
    Conflict = 'CONFLICT'


class DeltaAcceptedState(Enum):
    APPLIED = 'applied'
    CONFLICTS = 'conflicts'
    ERRORS = 'errors'


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
    def __init__(self, delta_file_id: str, project_id: str, version: str, deltas: List[Union[Dict, Delta]], files: List[str]):
        self.id = delta_file_id
        self.project_id = project_id
        self.version = version
        self.files = files
        self.deltas: List[Delta] = []

        for d in deltas:
            self.deltas.append(cast(Delta, d))
# /TYPE DEFINITIONS


# EXCEPTION DEFINITIONS\
class DeltaException(Exception):
    def __init__(self,
                 msg: str,
                 e_type: DeltaExceptionType = DeltaExceptionType.Error,
                 delta_file_id: str = None,
                 layer_id: str = None,
                 delta_idx: int = None,
                 delta_id: str = None,
                 feature_pk: str = None,
                 attr: str = None,
                 conflicts: List[str] = None,
                 method: DeltaMethod = None,
                 descr: str = None
                 ):
        super(DeltaException, self).__init__(msg)
        self.e_type = e_type
        self.delta_file_id = delta_file_id
        self.layer_id = layer_id
        self.delta_idx = delta_idx
        self.delta_id = delta_id
        self.feature_pk = feature_pk
        self.attr = attr
        self.method = method
        self.conflicts = conflicts
        self.descr = descr
# /EXCEPTION DEFINITIONS


BACKUP_SUFFIX = '.qfieldcloudbackup'


def project_decorator(f):
    def wrapper(opts: BaseOptions, *args, **kw):
        start_app()
        project = QgsProject.instance()
        project.setAutoTransaction(opts['transaction'])
        project.read(opts['project'])

        return f(project, opts, *args, **kw)  # type: ignore

    return wrapper


@project_decorator
def cmd_delta_apply(project: QgsProject, opts: DeltaOptions):
    try:
        deltas = load_delta_file(opts)

        if opts['transaction']:
            accepted_state = apply_deltas(project, deltas, inverse=opts['inverse'])
        else:
            accepted_state = apply_deltas_without_transaction(project, deltas, inverse=opts['inverse'])

        project.clear()
        if accepted_state == DeltaAcceptedState.CONFLICTS:
            logger.info('Accepted {} deltas with some conflicts'.format(len(deltas.deltas)))
            return 1
        elif accepted_state == DeltaAcceptedState.ERRORS:
            logger.info('Accepted {} deltas with some errors'.format(len(deltas.deltas)))
            return 2  # TODO change the error code
        elif accepted_state == DeltaAcceptedState.APPLIED:
            logger.info('Accepted {} deltas with no errors and conflicts'.format(len(deltas.deltas)))
            return 0
        else:
            logger.info('Accepted {} deltas, but unknown state'.format(len(deltas.deltas)))
            return 2  # TODO change the error code
    except DeltaException as err:
        exception_str = traceback.format_exc()
        err.descr = exception_str
        logger.exception('Delta exception: {}'.format(exception_str), err)
        return 2
    except Exception as err:
        exception_str = traceback.format_exc()
        logger.exception('Unknown exception: {}'.format(exception_str), err)
        return 2


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
    with open('./schemas/deltafile_01.json') as f:
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
    if 'delta_contents' not in args:
        return None

    obj = args['delta_contents']
    get_json_schema_validator().validate(obj)
    delta_file = DeltaFile(obj['id'], obj['project'], obj['version'], obj['deltas'], obj['files'])

    return delta_file


def delta_file_file_loader(args: DeltaOptions) -> Optional[DeltaFile]:
    """Get delta file contents from a filesystem file.

    Arguments:
        args {DeltaOptions} -- main options

    Returns:
        Optional[DeltaFile] -- loaded delta file on success, otherwise none
    """
    if not isinstance(args.get('delta_file'), str):
        return None

    delta_file_path = Path(args['delta_file'])  # type: ignore
    delta_file: DeltaFile

    with delta_file_path.open('r') as f:
        obj = json.load(f)
        get_json_schema_validator().validate(obj)
        delta_file = DeltaFile(obj['id'], obj['project'], obj['version'], obj['deltas'], obj['files'])

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

    assert deltas is not None, 'Unable to load deltas'

    return deltas


def apply_deltas_without_transaction(project: QgsProject, delta_file: DeltaFile, inverse: bool = False) -> DeltaAcceptedState:
    accepted_state = DeltaAcceptedState.APPLIED

    # apply deltas on each individual layer
    for idx, delta in enumerate(delta_file.deltas):
        layer_id: str = delta.get('sourceLayerId')
        layer: QgsVectorLayer = project.mapLayer(layer_id)

        try:
            if not isinstance(layer, QgsVectorLayer):
                raise DeltaException('No layer with id "{}"'.format(layer_id))

            if not layer.isEditable() and not layer.startEditing():
                raise DeltaException('Cannot start editing layer "{}"')

            delta = inverse_delta(delta) if inverse else delta

            if delta['method'] == DeltaMethod.CREATE.value:
                create_feature(layer, delta)
            elif delta['method'] == DeltaMethod.PATCH.value:
                patch_feature(layer, delta)
            elif delta['method'] == DeltaMethod.DELETE.value:
                delete_feature(layer, delta)
            else:
                raise DeltaException('Unknown delta method')

            if not layer.commitChanges():
                raise DeltaException('Failed to commit changes')

        except DeltaException as err:
            err.layer_id = err.layer_id or layer_id
            err.delta_idx = err.delta_idx or idx
            err.feature_pk = err.feature_pk or delta.get('sourcePk')
            err.method = err.method or delta.get('method')

            if err.e_type == DeltaExceptionType.Conflict:
                accepted_state = DeltaAcceptedState.CONFLICTS
                logger.warning('Conflicts while applying a single delta: {}'.format(str(err)), err)
            else:
                accepted_state = DeltaAcceptedState.ERRORS
                logger.warning('Error while applying a single delta: {}'.format(str(err)), err)

            if layer is not None and not layer.rollBack():
                logger.error('Failed to rollback layer "{}": {}'.format(layer_id, str(err)), err)
        except Exception as err:
            raise DeltaException('An error has been encountered while applying delta:' + str(err).replace('\n', ''),
                                 layer_id=layer.id(),
                                 delta_idx=idx,
                                 method=delta.get('method'),
                                 feature_pk=delta.get('sourcePk')) from err

    return accepted_state


def apply_deltas(project: QgsProject, delta_file: DeltaFile, inverse: bool = False) -> DeltaAcceptedState:
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
        transaction_id = conn_type + '$$$$$' + conn_string
        transcation_by_layer[layer_id] = transaction_id
        opened_transactions[transaction_id] = opened_transactions.get(transaction_id, [])
        opened_transactions[transaction_id].append(layer_id)

    # group all individual deltas by layer id
    for d in delta_file.deltas:
        layer_id = d['sourceLayerId']
        deltas_by_layer[layer_id] = deltas_by_layer.get(layer_id, [])
        deltas_by_layer[layer_id].append(d)
        layers_by_id[layer_id] = project.mapLayer(layer_id)

        if not isinstance(layers_by_id[layer_id], QgsVectorLayer):
            raise DeltaException('The layer does not exist: {}'.format(layer_id), layer_id=layer_id)

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
            raise DeltaException('Unable to backup file for layer {}'.format(layer_id), layer_id=layer_id, e_type=DeltaExceptionType.IO)

    modified_layer_ids: Set[LayerId] = set()

    # apply deltas on each individual layer
    for layer_id in deltas_by_layer.keys():
        # keep the try/except block inside the loop, so we can have the `layer_id` context
        try:
            if apply_deltas_on_layer(layers_by_id[layer_id], deltas_by_layer[layer_id], inverse):
                has_conflict = True

            modified_layer_ids.add(layer_id)
        except DeltaException as err:
            rollback_deltas(layers_by_id)
            err.layer_id = err.layer_id or layer_id
            err.delta_file_id = err.delta_file_id or delta_file.id
            raise err
        except Exception as err:
            rollback_deltas(layers_by_id)
            raise DeltaException('Failed to apply changes') from err

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
                    committed_layer_ids = set([*committed_layer_ids, *opened_transactions[transaction_id]])
                    del opened_transactions[transaction_id]
                else:
                    committed_layer_ids.add(layer_id)
            else:
                raise DeltaException('Failed to commit')
        except DeltaException:
            # all the modified layers must be rollbacked
            for layer_id in (modified_layer_ids - committed_layer_ids):
                if not layers_by_id[layer_id].rollBack():
                    logger.warning('Failed to rollback')

            rollback_deltas(layers_by_id, committed_layer_ids=committed_layer_ids)

    if not cleanup_backups(set(layers_by_id.keys())):
        logger.warning('Failed to cleanup backups, other than that - success')

    return DeltaAcceptedState.CONFLICTS if has_conflict else DeltaAcceptedState.APPLIED


def rollback_deltas(layers_by_id: Dict[LayerId, QgsVectorLayer], committed_layer_ids: Set[LayerId] = set()) -> bool:
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
                logger.warning('Unable to rollback layer {}'.format(layer.id()))

    # if there are already committed layers, restore the backup
    for layer_id in committed_layer_ids:
        if not layers_by_id.get(layer_id):
            logger.warning('Unable to restore original layer file, path missing: {}'.format(layer_id))
            continue

        layer_path = get_layer_path(layers_by_id[layer_id])
        layer_backup_path = get_backup_path(layer_path)

        # NOTE pathlib operations will raise in case of error
        try:
            layer_backup_path.rename(layer_path)
        except Exception as err:
            # TODO nothing better to do here?
            is_success = False
            logger.warning('Unable to restore original layer file: {}. Reason: {}'.format(layer_id, err))

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
            logger.warning('Unable to remove backup: {}. Reason: {}'.format(layer_backup_path, err))

    return is_success


def apply_deltas_on_layer(layer: QgsVectorLayer, deltas: List[Delta], inverse: bool, should_commit: bool = False) -> bool:
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

    Raises:
        DeltaException: whenever the changes cannot be applied

    Returns:
        bool -- indicates whether a conflict occurred
    """
    assert layer is not None
    assert layer.type() == QgsMapLayerType.VectorLayer

    has_conflict = False

    if not layer.isEditable() and not layer.startEditing():
        raise DeltaException('Cannot start editing')

    for idx, d in enumerate(deltas):
        assert d['sourceLayerId'] == layer.id()

        delta = inverse_delta(d) if inverse else d

        try:
            if delta['method'] == DeltaMethod.CREATE.value:
                create_feature(layer, delta)
            elif delta['method'] == DeltaMethod.PATCH.value:
                patch_feature(layer, delta)
            elif delta['method'] == DeltaMethod.DELETE.value:
                delete_feature(layer, delta)
            else:
                raise DeltaException('Unknown delta method')
        except DeltaException as err:
            # TODO I am lazy now and all these properties are set only here, but should be moved in depth
            err.layer_id = err.layer_id or layer.id()
            err.delta_idx = err.delta_idx or idx
            err.delta_id = err.delta_id or delta.get('id')
            err.method = err.method or delta.get('method')
            err.feature_pk = err.feature_pk or delta.get('sourcePk')

            if err.e_type == DeltaExceptionType.Conflict:
                has_conflict = True
                logger.warning('Conflicts while applying a single delta: {}'.format(str(err)), err)
            else:
                if not layer.rollBack():
                    # So unfortunate situation, that the only safe thing to do is to cancel the whole script
                    raise DeltaException("Cannot rollback layer changes: {}".format(layer.id())) from err

                raise err
        except Exception as err:
            if not layer.rollBack():
                # So unfortunate situation, that the only safe thing to do is to cancel the whole script
                raise DeltaException("Cannot rollback layer changes: {}".format(layer.id())) from err

            raise DeltaException('An error has been encountered while applying delta:' + str(err).replace('\n', ''),
                                 layer_id=layer.id(),
                                 delta_idx=idx,
                                 delta_id=delta.get('id'),
                                 method=delta.get('method'),
                                 descr=traceback.format_exc(),
                                 feature_pk=delta.get('sourcePk')) from err

    if should_commit and not layer.commitChanges():
        if not layer.rollBack():
            # So unfortunate situation, that the only safe thing to do is to cancel the whole script
            raise DeltaException("Cannot rollback layer changes: {}".format(layer.id()))

        raise DeltaException('Cannot commit changes')

    return has_conflict


def find_layer_pk(layer: QgsVectorLayer) -> Tuple[int, str]:
    fields = layer.fields()
    pk_attrs = [*layer.primaryKeyAttributes(), fields.indexFromName('fid')]
    # we assume the first index to be the primary key index... kinda stupid, but memory layers don't have primary key at all, but we use it on geopackages, but... snap!
    pk_attr_idx = pk_attrs[0]

    if pk_attr_idx == -1:
        return (-1, '')

    pk_attr_name = fields.at(pk_attr_idx).name()

    return (pk_attr_idx, pk_attr_name)


def get_feature(layer: QgsVectorLayer, feature_pk: FeaturePk) -> QgsFeature:
    _pk_attr_idx, pk_attr_name = find_layer_pk(layer)

    assert pk_attr_name

    expr = ' {} = {} '.format(QgsExpression.quotedColumnRef(pk_attr_name), QgsExpression.quotedValue(feature_pk))

    for f in layer.getFeatures(expr):
        return f

    return QgsFeature()


def create_feature(layer: QgsVectorLayer, delta: Delta) -> None:
    """Creates new feature in layer

    Arguments:
        layer {QgsVectorLayer} -- target layer. Must be in editing mode!
        delta {Delta} -- delta describing the created feature

    Raises:
        DeltaException: whenever the feature cannot be created
    """
    fields = layer.fields()
    new_feat_delta = delta['new']
    new_feat = QgsFeature(fields)

    if layer.isSpatial():
        if not isinstance(new_feat_delta['geometry'], str):
            raise DeltaException('The layer is spatial, but not WKT geometry has been provided')

        geometry = QgsGeometry.fromWkt(new_feat_delta['geometry'])

        if geometry.isNull():
            raise DeltaException('The layer is spatial, but the geometry is invalid')

        new_feat.setGeometry(geometry)
    else:
        if new_feat_delta['geometry']:
            logger.warning('The layer is not spatial, but geometry has been provided')

    if not new_feat.isValid():
        raise DeltaException('Unable to create a valid feature')

    new_feat_attrs = new_feat_delta.get('attributes')

    if new_feat_attrs:
        # `fid` is an extra field created during conversion to gpkg and makes this assert to fail.
        # if fields.size() < len(new_feat_attrs):
        #     raise DeltaException('The layer has less attributes than the provided by the delta')

        if new_feat_attrs:
            for field in fields:
                attr_name = field.name()

                if attr_name in new_feat_attrs:
                    attr_value = new_feat_attrs[attr_name]
                    new_feat[attr_name] = attr_value

    if not layer.addFeature(new_feat):
        raise DeltaException('Unable add new feature')


def patch_feature(layer: QgsVectorLayer, delta: Delta):
    """Patches a feature in layer

    Arguments:
        layer {QgsVectorLayer} -- target layer. Must be in edit mode!
        delta {Delta} -- delta describing the patch

    Raises:
        DeltaException: whenever the feature cannot be patched
    """
    new_feature_delta = delta['new']
    old_feature_delta = delta['old']
    old_feature = get_feature(layer, delta['sourcePk'])

    if not old_feature.isValid():
        raise DeltaException('Unable to find feature')

    conflicts = compare_feature(old_feature, old_feature_delta, True)

    if len(conflicts) != 0:
        raise DeltaException('There are conflicts with the already existing feature!', conflicts=conflicts, e_type=DeltaExceptionType.Conflict)

    if layer.isSpatial() and new_feature_delta.get('geometry') is not None:
        if not isinstance(new_feature_delta['geometry'], str):
            raise DeltaException('The layer is spatial, but not WKT geometry has been provided')

        if new_feature_delta['geometry'] == old_feature_delta['geometry']:
            logger.warning('The geometries of the new and the old features are the same, even though by spec they should not be provided in such case')

        geometry = QgsGeometry.fromWkt(new_feature_delta['geometry'])

        if geometry.isNull():
            raise DeltaException('The layer is spatial, but the geometry is invalid')

        if geometry.type() != old_feature.geometry().type():
            raise DeltaException('The provided geometry type differs from the layer geometry type')

        if not layer.changeGeometry(old_feature.id(), geometry, True):
            raise DeltaException('Unable to change geometry')
    else:
        if new_feature_delta.get('geometry'):
            logger.warning('The layer is not spatial, but geometry has been provided')

    fields = layer.fields()
    new_attrs = new_feature_delta.get('attributes') or {}
    old_attrs = old_feature_delta.get('attributes') or {}

    for attr_name, new_attr_value in new_attrs.items():
        # NOTE the old_attrs may be missing or empty
        old_attr_value = old_attrs.get(attr_name)

        if new_attrs[attr_name] == old_attr_value:
            logger.warning('The delta has features with the same value in both old and new values')
            continue

        if not layer.changeAttributeValue(old_feature.id(), fields.indexOf(attr_name), new_attr_value, old_attrs[attr_name], True):
            raise DeltaException('Unable to change attribute', attr=attr_name)


def delete_feature(layer: QgsVectorLayer, delta: Delta) -> None:
    """Deletes a feature from layer

    Arguments:
        layer {QgsVectorLayer} -- target layer. Must be in edit mode!
        delta {Delta} -- delta describing the deleted feature

    Raises:
        DeltaException: whenever the feature cannot be deleted
    """
    old_feature_delta = delta['old']
    old_feature = get_feature(layer, delta['sourcePk'])

    if not old_feature.isValid():
        raise DeltaException('Unable to find feature')

    conflicts = compare_feature(old_feature, old_feature_delta)

    if len(conflicts) != 0:
        raise DeltaException('There are conflicts with the already existing feature!', conflicts=conflicts, e_type=DeltaExceptionType.IO)

    if not layer.deleteFeature(old_feature.id()):
        raise DeltaException('Unable delete feature')


def compare_feature(feature: QgsFeature, delta_feature: DeltaFeature, is_delta_subset: bool = False) -> List[str]:
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

    delta_feature_attrs: Optional[Dict[str, Any]] = delta_feature.get('attributes')

    if delta_feature_attrs:
        delta_feature_attr_names = delta_feature_attrs.keys()
        feature_attr_names = feature.fields().names()

        # TODO reenable this, when it is clear what we do when there is property mismatch
        # if not is_delta_subset:
        #     for attr in feature_attr_names:
        #         if attr not in delta_feature_attr_names:
        #             conflicts.append('There is an attribute in the original feature that is not available in the delta: {}'.format(attr))

        for attr in delta_feature_attr_names:
            if attr not in feature_attr_names:
                # TODO reenable this, when it is clear what we do when there is property mismatch
                # conflicts.append('There is an attribute in the delta that is not available in the original feature: {}'.format(attr))
                continue

            if feature.attribute(attr) != delta_feature_attrs[attr]:
                conflicts.append('There is an attribute that has different value: {}'.format(attr))

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
    data_source_decoded = QgsProviderRegistry.instance().decodeUri('ogr', data_source_uri)
    return Path(data_source_decoded['path'])


def get_backup_path(path: Path) -> Path:
    """Returns a `Path` object of with backup suffix

    Arguments:
        path {Path} -- target path

    Returns:
        Path -- suffixed path
    """
    return Path(str(path) + BACKUP_SUFFIX)


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
    copy['old'], copy['new'] = delta['new'], delta['old']

    if copy['method'] == DeltaMethod.CREATE.name:
        copy['method'] = DeltaMethod.DELETE.name
    elif copy['method'] == DeltaMethod.DELETE.name:
        copy['method'] = DeltaMethod.CREATE.name

    return cast(Delta, copy)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='COMMAND',
        description='',
        formatter_class=argparse.RawDescriptionHelpFormatter,  # type: ignore
        epilog=textwrap.dedent('''
            example:
                # apply deltas on a project
                ./apply_delta.py delta apply ./path/to/project.qgs ./path/to/delta.json

                # rollback deltas on a project
                ./apply_delta.py delta apply --inverse ./path/to/project.qgs ./path/to/delta.json

                # rollback deltas on a project
                ./apply_delta.py backup cleanup
        '''),
    )
    parser.add_argument('--skip-csv-header', action='store_true', help='Skip writing CSV header in the log file')

    subparsers = parser.add_subparsers(dest='cmd0')

    # deltas
    parser_delta = subparsers.add_parser('delta', help='rollback a delta file on a project')
    delta_subparsers = parser_delta.add_subparsers(dest='cmd1')

    parser_delta_apply = delta_subparsers.add_parser('apply', help='apply a delta file on a project')
    parser_delta_apply.add_argument('project', type=str, help='Path to QGIS project')
    parser_delta_apply.add_argument('delta_file', type=str, help='Path to delta file')
    parser_delta_apply.add_argument('--inverse', action='store_true', help='Inverses the direction of the deltas. Makes the delta `old` to `new` and `new` to `old`. Mainly used to rollback the applied changes using the same delta file..')
    parser_delta_apply.add_argument('--transaction', action='store_true', help='Apply individual deltas in the deltafile in the "all-or-nothing" manner, with transaction mode enabled')
    parser_delta_apply.set_defaults(func=cmd_delta_apply)
    # /deltas

    # backup
    parser_backup = subparsers.add_parser('backup', help='rollback a delta file on a project')
    backup_subparsers = parser_backup.add_subparsers(dest='cmd1')

    parser_backup_cleanup = backup_subparsers.add_parser('cleanup', help='rollback a delta file on a project')
    parser_backup_cleanup.add_argument('project', type=str, help='Path to QGIS project')
    parser_backup_cleanup.add_argument('--transaction', action='store_true', help='Apply individual deltas in the deltafile in the "all-or-nothing" manner, with transaction mode enabled')
    parser_backup_cleanup.set_defaults(func=cmd_backup_cleanup)

    parser_backup_rollback = backup_subparsers.add_parser('rollback', help='rollback a delta file on a project')
    parser_backup_rollback.add_argument('project', type=str, help='Path to QGIS project')
    parser_backup_rollback.add_argument('--transaction', action='store_true', help='Apply individual deltas in the deltafile in the "all-or-nothing" manner, with transaction mode enabled')
    parser_backup_rollback.set_defaults(func=cmd_backup_rollback)
    # /backup

    args = parser.parse_args()

    logging.root.handlers[0].setFormatter(CsvFormatter(args.skip_csv_header))

    if 'func' in args:
        args.func(vars(args))  # type: ignore
    else:
        parser.parse_args(['-h'])
