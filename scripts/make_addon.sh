#!/bin/bash

PACKAGE_NAME=ijim
SRC_DIR="../${PACKAGE_NAME}"
OUT_DIR="output/"

FILE_FILTER="__test.py"
EXT_FILTER="blend|blend1"
FOLDER_FILTER="__pycache__"


mkdir -p $OUT_DIR
cp -rf $SRC_DIR $OUT_DIR

filter(){
    for path in "$1"/* ; do
        if [ -d "$path" ]
        then
            dirname=$(basename -- "$path")
            if [[ "$dirname" =~ ^($FOLDER_FILTER)$ ]]; then
                rm -rf $path
            else
                filter "$path"
            fi
        else
            filename=$(basename -- "$path")
            extension="${filename##*.}"
            if [[ "$filename" =~ ^($FILE_FILTER)$ || "$extension" =~ ^($EXT_FILTER)$ ]]; then
                rm $path
            fi
        fi
    done
}

filter "$OUT_DIR/${PACKAGE_NAME}"

pushd "$OUT_DIR"
[ -e "${PACKAGE_NAME}".zip ] && rm "${PACKAGE_NAME}".zip
zip -rq "${PACKAGE_NAME}"{.zip,}
rm -rf "${PACKAGE_NAME}"
popd