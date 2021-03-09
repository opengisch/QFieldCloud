#!/bin/bash -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "BEGIN TESTS"
$DIR/../apply_deltas.py delta apply $DIR/testdata/project2apply/project.qgs $DIR/testdata/project2apply/deltas/singlelayer_singledelta.json
$DIR/../apply_deltas.py delta apply --inverse $DIR/testdata/project2apply/project.qgs $DIR/testdata/project2apply/deltas/singlelayer_singledelta.json
$DIR/../apply_deltas.py delta apply $DIR/testdata/project2apply/project.qgs $DIR/testdata/project2apply/deltas/singlelayer_multidelta.json
$DIR/../apply_deltas.py delta apply --inverse $DIR/testdata/project2apply/project.qgs $DIR/testdata/project2apply/deltas/singlelayer_multidelta.json
$DIR/../apply_deltas.py delta apply $DIR/testdata/project2apply/project.qgs $DIR/testdata/project2apply/deltas/multilayer_multidelta.json
$DIR/../apply_deltas.py delta apply --inverse $DIR/testdata/project2apply/project.qgs $DIR/testdata/project2apply/deltas/multilayer_multidelta.json
echo "END TESTS"
