#!/bin/bash
set -eo pipefail
if [[ "$1" == "" ]] ; then
    echo "Usage: $0 <PROJECT_PATH>"
    exit 1
fi
PROJECT_PATH="$1"

# Detect architecture
IS_ARM64=false
if [[ "$CIBW_ARCHS" == *"ARM64"* ]] || [[ "$CIBW_ARCHS" == *"arm64"* ]] || [[ "$(uname -m)" == "arm64" ]] || [[ "$(uname -m)" == "aarch64" ]]; then
    IS_ARM64=true
fi

# Set architecture-specific variables
if [[ "$IS_ARM64" == true ]]; then
    ZLIB_PACKAGE="zlib-msvc-arm64"
    HDF5_VSVERSION="17-arm64"
    ARCH_SUFFIX="arm64"
else
    ZLIB_PACKAGE="zlib-msvc-x64"
    HDF5_VSVERSION="17-64"
    ARCH_SUFFIX="x64"
fi

# nuget
nuget install "$ZLIB_PACKAGE" -ExcludeVersion -OutputDirectory "$PROJECT_PATH"
EXTRA_PATH="$PROJECT_PATH\\$ZLIB_PACKAGE\\build\\native\\bin_release"
export PATH="$PATH:$EXTRA_PATH"
export CL="/I$PROJECT_PATH\\$ZLIB_PACKAGE\\build\\native\\include"
export LINK="/LIBPATH:$PROJECT_PATH\\$ZLIB_PACKAGE\\build\\native\\lib_release"
export ZLIB_ROOT="$PROJECT_PATH\\$ZLIB_PACKAGE\\build\\native"

# HDF5
export HDF5_VERSION="1.14.6"
export HDF5_VSVERSION="$HDF5_VSVERSION"
export HDF5_DIR="$PROJECT_PATH/cache/hdf5/$HDF5_VERSION-$ARCH_SUFFIX"
pip install requests
python $PROJECT_PATH/ci/get_hdf5_win.py

if [[ "$GITHUB_ENV" != "" ]] ; then
    # PATH on windows is special
    echo "$EXTRA_PATH" | tee -a $GITHUB_PATH
    echo "CL=$CL" | tee -a $GITHUB_ENV
    echo "LINK=$LINK" | tee -a $GITHUB_ENV
    echo "ZLIB_ROOT=$ZLIB_ROOT" | tee -a $GITHUB_ENV
    echo "HDF5_DIR=$HDF5_DIR" | tee -a $GITHUB_ENV
fi
