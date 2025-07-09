# -*- coding: utf-8 -*-
"""
Script for downloading and building HDF5 on Windows
This does not support MPI, nor non-Windows OSes

This script may not completely clean up after itself; it is designed to run in a
CI environment which is thrown away each time.
"""

from os import environ, makedirs, walk, getcwd, chdir
from os.path import join as pjoin, exists, basename, dirname, abspath
from tempfile import TemporaryFile, TemporaryDirectory
from sys import exit, stderr
from shutil import copy, rmtree
from glob import glob
from subprocess import run
from zipfile import ZipFile
import requests

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
    "9-64": "Visual Studio 9 2008 Win64",
    "10-64": "Visual Studio 10 2010 Win64",
    "14-64": "Visual Studio 14 2015 Win64",
    "15-64": "Visual Studio 15 2017 Win64",
    "16-64": "Visual Studio 16 2019",
    "17-64": "Visual Studio 17 2022",
    "17-arm64": "Visual Studio 17 2022",
}


def download_hdf5(version, outfile):
    zip_fmt1 = "hdf5-" + version.replace(".", "_") + ".zip"
    zip_fmt2 = "hdf5_" + version.replace("-", ".") + ".zip"
    files = [HDF5_URL.format(zip_file=zip_fmt1),
             HDF5_URL.format(zip_file=zip_fmt2)]
    
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


def build_hdf5(version, hdf5_file, install_path, cmake_generator, use_prefix, dl_zip):
    try:
        run(["cmake", "--version"], check=True)
        with TemporaryDirectory() as hdf5_extract_path:
            with ZipFile(hdf5_file) as z:
                z.extractall(hdf5_extract_path)

            old_dir = getcwd()
            temp_build_dir = TemporaryDirectory()
            new_dir = temp_build_dir.name

            try:
                chdir(new_dir)
                prefix_args = CMAKE_HDF5_LIBRARY_PREFIX if use_prefix else []
                generator_args = []

                if cmake_generator:
                    generator_args += ["-G", cmake_generator]
                    if "arm64" in cmake_generator.lower():
                        generator_args += ["-A", "ARM64"]

                cfg_cmd = CMAKE_CONFIGURE_CMD + [
                    get_cmake_install_path(install_path),
                    get_cmake_config_path(hdf5_extract_path, dl_zip),
                ] + generator_args + prefix_args

                print(f"Configuring HDF5 version {version}...", file=stderr)
                print(">> " + ' '.join(cfg_cmd), file=stderr)
                result = run(cfg_cmd, capture_output=True, text=True)
                print(result.stdout, file=stderr)
                print(result.stderr, file=stderr)
                if result.returncode != 0:
                    raise RuntimeError("CMake configure failed")

                build_cmd = CMAKE_BUILD_CMD + ['.'] + CMAKE_INSTALL_ARG
                print(f"Building HDF5 version {version}...", file=stderr)
                print(">> " + ' '.join(build_cmd), file=stderr)
                result = run(build_cmd, capture_output=True, text=True)
                print(result.stdout, file=stderr)
                print(result.stderr, file=stderr)
                if result.returncode != 0:
                    raise RuntimeError("CMake build failed")

                print(f"Installed HDF5 version {version} to {install_path}", file=stderr)
            finally:
                chdir(old_dir)
                try:
                    temp_build_dir.cleanup()
                except Exception as e:
                    print(f"Warning: Failed to cleanup temp dir: {e}", file=stderr)

    except Exception as e:
        print(f"❌ Build failed: {e}", file=stderr)
        raise

    # Copy DLLs to lib folder
    for f in glob(pjoin(install_path, 'bin', '*.dll')):
        copy(f, pjoin(install_path, 'lib'))


def get_cmake_config_path(extract_point, zip_file):
    dir_suffix = basename(zip_file).removesuffix(".zip")
    return pjoin(extract_point, REL_PATH_TO_CMAKE_CFG.format(dir_suffix=dir_suffix))


def get_cmake_install_path(install_path):
    if install_path is not None:
        return CMAKE_INSTALL_PATH_ARG.format(install_path=install_path)
    return ' '


def hdf5_install_cached(install_path):
    return exists(pjoin(install_path, "lib", "hdf5.dll"))


def main():
    install_path = environ.get("HDF5_DIR")
    version = environ.get("HDF5_VERSION", DEFAULT_VERSION)
    vs_version = environ.get("HDF5_VSVERSION")
    use_prefix = environ.get("H5PY_USE_PREFIX") is not None

    if install_path and not exists(install_path):
        makedirs(install_path)

    cmake_generator = None
    if vs_version:
        cmake_generator = VSVERSION_TO_GENERATOR.get(vs_version)
        if vs_version == '9-64':
            run("ci\\appveyor\\vs2008_patch\\setup_x64.bat")

    if not hdf5_install_cached(install_path):
        with TemporaryFile() as f:
            dl_zip = download_hdf5(version, f)
            f.seek(0)
            build_hdf5(version, f, install_path, cmake_generator, use_prefix, dl_zip)
    else:
        print("Using cached HDF5", file=stderr)

    if install_path:
        print("HDF5 files installed:", file=stderr)
        for dirpath, _, filenames in walk(install_path):
            for file in filenames:
                print(" * " + pjoin(dirpath, file))


if __name__ == '__main__':
    main()
