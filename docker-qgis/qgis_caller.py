import os
import argparse

from qgis.core import QgsProject, QgsRectangle, QgsOfflineEditing
from qgis.testing import start_app

from qfieldsync.core.offline_converter import OfflineConverter


start_app()


def export(args):
    project = QgsProject.instance()
    if not os.path.exists(args.path):
        raise FileNotFoundError(args.path)

    if not project.read(os.path.join(args.path)):
        raise Exception("Unable to open file with QGIS: {}".format(args.path))

    # TODO: get extent from the qfieldsync project settings
    extent = QgsRectangle()
    offline_editing = QgsOfflineEditing()
    offline_converter = OfflineConverter(
        project, args.out, extent, offline_editing)
    offline_converter.convert()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='COMMAND')

    subparsers = parser.add_subparsers(dest='cmd')

    parser_export = subparsers.add_parser('export', help='export a project')
    parser_export.add_argument('path', type=str, help='source project')
    parser_export.add_argument('out', type=str, help='output directory')
    parser_export.set_defaults(func=export)

    args = parser.parse_args()
    args.func(args)
