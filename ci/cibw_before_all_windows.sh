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
    VCPKG_TRIPLET="arm64-windows"
    HDF5_VSVERSION="17-arm64"
    ARCH_SUFFIX="arm64"
else
    VCPKG_TRIPLET="x64-windows"
    HDF5_VSVERSION="17-64"
    ARCH_SUFFIX="x64"
fi

# Install zlib via vcpkg or nuget
if [[ "$IS_ARM64" == true ]]; then
    # Use vcpkg for ARM64
    git clone https://github.com/Microsoft/vcpkg.git "$PROJECT_PATH/vcpkg"
    "$PROJECT_PATH/vcpkg/bootstrap-vcpkg.bat"
    "$PROJECT_PATH/vcpkg/vcpkg.exe" install zlib:$VCPKG_TRIPLET
    ZLIB_ROOT="$PROJECT_PATH\\vcpkg\\installed\\$VCPKG_TRIPLET"
    EXTRA_PATH="$ZLIB_ROOT\\bin"
    export PATH="$PATH:$EXTRA_PATH"
    export CL="/I$ZLIB_ROOT\\include"
    export LINK="/LIBPATH:$ZLIB_ROOT\\lib"
    export ZLIB_ROOT="$ZLIB_ROOT"
else
    # Use nuget for x64
    nuget install zlib-msvc-x64 -ExcludeVersion -OutputDirectory "$PROJECT_PATH"
    EXTRA_PATH="$PROJECT_PATH\\zlib-msvc-x64\\build\\native\\bin_release"
    export PATH="$PATH:$EXTRA_PATH"
    export CL="/I$PROJECT_PATH\\zlib-msvc-x64\\build\\native\\include"
    export LINK="/LIBPATH:$PROJECT_PATH\\zlib-msvc-x64\\build\\native\\lib_release"
    export ZLIB_ROOT="$PROJECT_PATH\\zlib-msvc-x64\\build\\native"
fi

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
