#!/bin/sh
BASEDIR=$(dirname "$0")
PYTHONPATH=$BASEDIR/stdlib.zip:$PYTHONPATH $BASEDIR/_python "$@"
