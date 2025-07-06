# -*- coding: utf-8 -*-
"""
Script for downloading and building HDF5 on Windows
This does not support MPI, nor non-Windows OSes

This script may not completely clean up after itself, it is designed to run in a
CI environment which thrown away each time
"""

from os import environ, makedirs, walk, getcwd, chdir
from os.path import join as pjoin, exists, basename, dirname, abspath
from tempfile import TemporaryFile, TemporaryDirectory
from sys import exit, stderr
from shutil import copy
from glob import glob
from subprocess import run
from zipfile import ZipFile
import requests
import platform

HDF5_URL = "https://github.com/HDFGroup/hdf5/archive/refs/tags/{zip_file}"
ZLIB_ROOT = environ.get('ZLIB_ROOT')

CI_DIR = dirname(abspath(__file__))

CMAKE_CONFIGURE_CMD = [
    "cmake", "-DBUILD_SHARED_LIBS:BOOL=ON", "-DCMAKE_BUILD_TYPE:STRING=RELEASE",
    "-DHDF5_BUILD_CPP_LIB=OFF", "-DHDF5_BUILD_HL_LIB=ON",
    "-DHDF5_BUILD_TOOLS:BOOL=OFF", "-DBUILD_TESTING:BOOL=OFF",
]
if ZLIB_ROOT:
    CMAKE_CONFIGURE_CMD += [
        "-DHDF5_ENABLE_Z_LIB_SUPPORT=ON",
        f"-DZLIB_INCLUDE_DIR={ZLIB_ROOT}\\include",
        f"-DZLIB_LIBRARY_RELEASE={ZLIB_ROOT}\\lib_release\\zlib.lib",
        f"-DZLIB_LIBRARY_DEBUG={ZLIB_ROOT}\\lib_debug\\zlibd.lib",
    ]
CMAKE_BUILD_CMD = ["cmake", "--build"]
CMAKE_INSTALL_ARG = ["--target", "install", '--config', 'Release']
CMAKE_INSTALL_PATH_ARG = "-DCMAKE_INSTALL_PREFIX={install_path}"
CMAKE_HDF5_LIBRARY_PREFIX = ["-DHDF5_EXTERNAL_LIB_PREFIX=h5py_"]
REL_PATH_TO_CMAKE_CFG = "hdf5-{dir_suffix}"
DEFAULT_VERSION = '1.12.2'
VSVERSION_TO_GENERATOR = {
    "9": "Visual Studio 9 2008",
    "10": "Visual Studio 10 2010",
    "14": "Visual Studio 14 2015",
    "15": "Visual Studio 15 2017",
    "16": "Visual Studio 16 2019",
    "17": "Visual Studio 17 2022",
    "9-64": "Visual Studio 9 2008 Win64",
    "10-64": "Visual Studio 10 2010 Win64",
    "14-64": "Visual Studio 14 2015 Win64",
    "15-64": "Visual Studio 15 2017 Win64",
    "16-64": "Visual Studio 16 2019",
    "17-64": "Visual Studio 17 2022",
    # ARM64 support added for VS 2019 and later
    "16-arm64": "Visual Studio 16 2019",
    "17-arm64": "Visual Studio 17 2022",
}

# Architecture mapping for CMAKE_GENERATOR_PLATFORM
VSVERSION_TO_ARCH = {
    "16-arm64": "ARM64",
    "17-arm64": "ARM64",
}


def get_default_vs_version():
    """Determine default Visual Studio version based on system architecture"""
    machine = platform.machine().lower()
    if machine in ['arm64', 'aarch64']:
        return "17-arm64"  # Default to VS 2022 for ARM64
    else:
        return "17-64"  # Default to VS 2022 for x64


def download_hdf5(version, outfile):
    zip_fmt1 = "hdf5-" + version.replace(".", "_") + ".zip"
    zip_fmt2 = "hdf5_" + version.replace("-", ".") + ".zip"
    files = [HDF5_URL.format(zip_file=zip_fmt1),
             HDF5_URL.format(zip_file=zip_fmt2),
             ]

    for file in files:
        print(f"Downloading hdf5 from {file} ...", file=stderr)
        r = requests.get(file, stream=True)
        try:
            r.raise_for_status()
        except requests.HTTPError:
            print(f"Failed to download hdf5 from {file}", file=stderr)
            continue
        else:
            for chunk in r.iter_content(chunk_size=None):
                outfile.write(chunk)
            print(f"Successfully downloaded hdf5 from {file}", file=stderr)
            return file

    msg = (f"Cannot download HDF5 source ({version}) from any of the "
           f"following URLs: {[f for f in files]}")
    raise RuntimeError(msg)


def build_hdf5(version, hdf5_file, install_path, cmake_generator, use_prefix,
               dl_zip, vs_version=None):
    try:
        run(["cmake", "--version"])  # Show what version of cmake we'll use
        with TemporaryDirectory() as hdf5_extract_path:
            generator_args = []
            if cmake_generator is not None:
                generator_args = ["-G", cmake_generator]
                
                # Add architecture platform for ARM64 builds
                if vs_version and vs_version in VSVERSION_TO_ARCH:
                    arch = VSVERSION_TO_ARCH[vs_version]
                    generator_args.extend(["-A", arch])
                    print(f"Building for architecture: {arch}", file=stderr)
            
            prefix_args = CMAKE_HDF5_LIBRARY_PREFIX if use_prefix else []

            with ZipFile(hdf5_file) as z:
                z.extractall(hdf5_extract_path)

            old_dir = getcwd()

            with TemporaryDirectory() as new_dir:
                chdir(new_dir)
                cfg_cmd = CMAKE_CONFIGURE_CMD + [
                    get_cmake_install_path(install_path),
                    get_cmake_config_path(hdf5_extract_path, dl_zip),
                ] + generator_args + prefix_args
                print("Configuring HDF5 version {version}...".format(version=version))
                print(' '.join(cfg_cmd), file=stderr)
                run(cfg_cmd, check=True)

                build_cmd = CMAKE_BUILD_CMD + [
                    '.',
                ] + CMAKE_INSTALL_ARG
                print("Building HDF5 version {version}...".format(version=version))
                print(' '.join(build_cmd), file=stderr)
                run(build_cmd, check=True)

                print("Installed HDF5 version {version} to {install_path}".format(
                    version=version, install_path=install_path,
                ), file=stderr)
                chdir(old_dir)
    except OSError as e:
        if e.winerror == 145:
            print("Hit the rmtree race condition, continuing anyway...", file=stderr)
        else:
            raise
    for f in glob(pjoin(install_path, 'bin/*.dll')):
        copy(f, pjoin(install_path, 'lib'))


def get_cmake_config_path(extract_point, zip_file):
    dir_suffix = basename(zip_file).removesuffix(".zip")
    return pjoin(extract_point, REL_PATH_TO_CMAKE_CFG.format(dir_suffix=dir_suffix))


def get_cmake_install_path(install_path):
    if install_path is not None:
        return CMAKE_INSTALL_PATH_ARG.format(install_path=install_path)
    return ' '


def hdf5_install_cached(install_path):
    if exists(pjoin(install_path, "lib", "hdf5.dll")):
        return True
    return False


def validate_arm64_environment():
    """Validate that the environment supports ARM64 builds"""
    machine = platform.machine().lower()
    if machine in ['arm64', 'aarch64']:
        print(f"Detected ARM64 architecture: {machine}", file=stderr)
        return True
    else:
        print(f"Detected x64 architecture: {machine}", file=stderr)
        return False


def main():
    install_path = environ.get("HDF5_DIR")
    version = environ.get("HDF5_VERSION", DEFAULT_VERSION)
    vs_version = environ.get("HDF5_VSVERSION")
    use_prefix = True if environ.get("H5PY_USE_PREFIX") is not None else False

    # Auto-detect architecture if no VS version specified
    if vs_version is None:
        vs_version = get_default_vs_version()
        print(f"Auto-detected VS version: {vs_version}", file=stderr)

    # Validate ARM64 environment
    is_arm64_host = validate_arm64_environment()
    is_arm64_build = vs_version and "arm64" in vs_version
    
    if is_arm64_build and not is_arm64_host:
        print("Warning: Building ARM64 binaries on non-ARM64 host", file=stderr)
    
    if install_path is not None:
        if not exists(install_path):
            makedirs(install_path)
    
    if vs_version is not None:
        if vs_version not in VSVERSION_TO_GENERATOR:
            raise ValueError(f"Unsupported Visual Studio version: {vs_version}. "
                           f"Supported versions: {list(VSVERSION_TO_GENERATOR.keys())}")
        
        cmake_generator = VSVERSION_TO_GENERATOR[vs_version]
        
        # Special handling for VS 2008 x64
        if vs_version == '9-64':
            # Needed for
            # http://help.appveyor.com/discussions/kb/38-visual-studio-2008-64-bit-builds
            run("ci\\appveyor\\vs2008_patch\\setup_x64.bat")
    else:
        cmake_generator = None

    if not hdf5_install_cached(install_path):
        with TemporaryFile() as f:
            dl_zip = download_hdf5(version, f)
            build_hdf5(version, f, install_path, cmake_generator, use_prefix,
                       dl_zip, vs_version)
    else:
        print("using cached hdf5", file=stderr)
    if install_path is not None:
        print("hdf5 files: ", file=stderr)
        for dirpath, dirnames, filenames in walk(install_path):
            for file in filenames:
                print(" * " + pjoin(dirpath, file))


if __name__ == '__main__':
    main()
