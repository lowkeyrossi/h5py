#!/bin/bash
set -eo pipefail

if [[ "$1" == "" ]]; then
    echo "Usage: $0 <PROJECT_PATH>"
    exit 1
fi

PROJECT_PATH="$1"
echo "PROJECT_PATH: $PROJECT_PATH"

echo "========== Detecting Architecture =========="
echo "uname -m: $(uname -m)"
echo "PROCESSOR_ARCHITECTURE: $PROCESSOR_ARCHITECTURE"
echo "CIBW_ARCH: $CIBW_ARCH"
echo "CIBW_ARCHS: $CIBW_ARCHS"

IS_ARM64=false
if [[ "$CIBW_ARCHS" == *"ARM64"* ]] || [[ "$CIBW_ARCHS" == *"arm64"* ]] || [[ "$(uname -m)" == "arm64" ]] || [[ "$(uname -m)" == "aarch64" ]]; then
    IS_ARM64=true
fi
echo "Detected ARM64 target: $IS_ARM64"

# Set variables
if [[ "$IS_ARM64" == true ]]; then
    VCPKG_TRIPLET="arm64-windows"
    HDF5_VSVERSION="17-arm64"
    ARCH_SUFFIX="arm64"
else
    VCPKG_TRIPLET="x64-windows"
    HDF5_VSVERSION="17-64"
    ARCH_SUFFIX="x64"
fi

# Install zlib
if [[ "$IS_ARM64" == true ]]; then
    echo "========== Installing zlib via vcpkg for $VCPKG_TRIPLET =========="
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
    echo "========== Installing zlib via NuGet for x64 =========="
    nuget install zlib-msvc-x64 -ExcludeVersion -OutputDirectory "$PROJECT_PATH"
    ZLIB_ROOT="$PROJECT_PATH\\zlib-msvc-x64\\build\\native"
    EXTRA_PATH="$ZLIB_ROOT\\bin_release"
    export PATH="$PATH:$EXTRA_PATH"
    export CL="/I$ZLIB_ROOT\\include"
    export LINK="/LIBPATH:$ZLIB_ROOT\\lib_release"
    export ZLIB_ROOT="$ZLIB_ROOT"
fi

# Debug output
echo ""
echo "========== DEBUG: Environment Variables =========="
echo "PATH=$PATH"
echo "CL=$CL"
echo "LINK=$LINK"
echo "ZLIB_ROOT=$ZLIB_ROOT"
echo "HDF5_DIR (will be set below)=$PROJECT_PATH/cache/hdf5/1.14.6-$ARCH_SUFFIX"
echo "Checking for zlib.lib at: ${ZLIB_ROOT}\\lib\\zlib.lib or \\lib_release\\zlib.lib"
ls "$ZLIB_ROOT"/*/zlib.lib || echo "⚠️ zlib.lib NOT FOUND in expected locations"

# HDF5
export HDF5_VERSION="1.14.6"
export HDF5_VSVERSION="$HDF5_VSVERSION"
export HDF5_DIR="$PROJECT_PATH/cache/hdf5/$HDF5_VERSION-$ARCH_SUFFIX"
pip install requests
python "$PROJECT_PATH/ci/get_hdf5_win.py"

# Export to GitHub env if running in CI
if [[ "$GITHUB_ENV" != "" ]]; then
    echo "$EXTRA_PATH" | tee -a "$GITHUB_PATH"
    echo "CL=$CL" | tee -a "$GITHUB_ENV"
    echo "LINK=$LINK" | tee -a "$GITHUB_ENV"
    echo "ZLIB_ROOT=$ZLIB_ROOT" | tee -a "$GITHUB_ENV"
    echo "HDF5_DIR=$HDF5_DIR" | tee -a "$GITHUB_ENV"
fi
