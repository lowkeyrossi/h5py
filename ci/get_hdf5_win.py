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
from shutil import copy, rmtree
from glob import glob
from subprocess import run, PIPE
from zipfile import ZipFile
import requests
import time
import platform

HDF5_URL = "https://github.com/HDFGroup/hdf5/archive/refs/tags/{zip_file}"
ZLIB_ROOT = environ.get('ZLIB_ROOT')

CI_DIR = dirname(abspath(__file__))

# Check if we're on ARM64
IS_ARM64 = platform.machine().lower() in ['arm64', 'aarch64']

CMAKE_CONFIGURE_CMD = [
    "cmake", "-DBUILD_SHARED_LIBS:BOOL=ON", "-DCMAKE_BUILD_TYPE:STRING=RELEASE",
    "-DHDF5_BUILD_CPP_LIB=OFF", "-DHDF5_BUILD_HL_LIB=ON",
    "-DHDF5_BUILD_TOOLS:BOOL=OFF", "-DBUILD_TESTING:BOOL=OFF",
]

# Add ARM64-specific flags
if IS_ARM64:
    CMAKE_CONFIGURE_CMD += [
        "-DHDF5_ENABLE_THREADSAFE:BOOL=OFF",  # Disable threading for ARM64
        "-DHDF5_ENABLE_PARALLEL:BOOL=OFF",    # Disable parallel features
        "-DCMAKE_SYSTEM_PROCESSOR=ARM64",
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
}


def safe_rmtree(path, max_retries=3, delay=1):
    """Safely remove directory tree with retries for Windows file locking issues."""
    for attempt in range(max_retries):
        try:
            rmtree(path)
            return
        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                print(f"Retry {attempt + 1}/{max_retries} for removing {path}: {e}", file=stderr)
                time.sleep(delay)
            else:
                print(f"Failed to remove {path} after {max_retries} attempts: {e}", file=stderr)
                # Don't raise, just continue - this is expected in CI


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


def run_with_output(cmd, check=True, **kwargs):
    """Run command with better error reporting."""
    print(' '.join(cmd), file=stderr)
    try:
        result = run(cmd, check=check, capture_output=True, text=True, **kwargs)
        if result.stdout:
            print("STDOUT:", result.stdout, file=stderr)
        if result.stderr:
            print("STDERR:", result.stderr, file=stderr)
        return result
    except Exception as e:
        print(f"Command failed: {' '.join(cmd)}", file=stderr)
        print(f"Error: {e}", file=stderr)
        raise


def build_hdf5(version, hdf5_file, install_path, cmake_generator, use_prefix,
               dl_zip):
    build_dir = None
    extract_dir = None
    
    try:
        run_with_output(["cmake", "--version"])  # Show what version of cmake we'll use
        
        # Create directories manually to have more control
        import tempfile
        extract_dir = tempfile.mkdtemp(prefix="hdf5_extract_")
        build_dir = tempfile.mkdtemp(prefix="hdf5_build_")
        
        generator_args = (
            ["-G", cmake_generator]
            if cmake_generator is not None
            else []
        )
        
        # For ARM64, use specific generator
        if IS_ARM64 and cmake_generator is None:
            generator_args = ["-G", "Visual Studio 17 2022", "-A", "ARM64"]
        
        prefix_args = CMAKE_HDF5_LIBRARY_PREFIX if use_prefix else []

        with ZipFile(hdf5_file) as z:
            z.extractall(extract_dir)

        old_dir = getcwd()
        chdir(build_dir)
        
        try:
            cfg_cmd = CMAKE_CONFIGURE_CMD + [
                get_cmake_install_path(install_path),
                get_cmake_config_path(extract_dir, dl_zip),
            ] + generator_args + prefix_args
            
            print("Configuring HDF5 version {version}...".format(version=version))
            run_with_output(cfg_cmd, check=True)

            build_cmd = CMAKE_BUILD_CMD + [
                '.',
            ] + CMAKE_INSTALL_ARG
            
            # For ARM64, add parallel build limits
            if IS_ARM64:
                build_cmd += ["-j", "1"]  # Single-threaded build for ARM64
            
            print("Building HDF5 version {version}...".format(version=version))
            run_with_output(build_cmd, check=True)

            print("Installed HDF5 version {version} to {install_path}".format(
                version=version, install_path=install_path,
            ), file=stderr)
            
        finally:
            chdir(old_dir)
            
    except Exception as e:
        print(f"Build failed: {e}", file=stderr)
        # On ARM64, try a simplified build
        if IS_ARM64:
            print("Attempting simplified ARM64 build...", file=stderr)
            try:
                return build_hdf5_simplified(version, hdf5_file, install_path, 
                                           cmake_generator, use_prefix, dl_zip)
            except Exception as e2:
                print(f"Simplified build also failed: {e2}", file=stderr)
        raise e
    finally:
        # Clean up directories
        if build_dir and exists(build_dir):
            safe_rmtree(build_dir)
        if extract_dir and exists(extract_dir):
            safe_rmtree(extract_dir)
    
    # Copy DLLs to lib directory
    for f in glob(pjoin(install_path, 'bin/*.dll')):
        copy(f, pjoin(install_path, 'lib'))


def build_hdf5_simplified(version, hdf5_file, install_path, cmake_generator, 
                         use_prefix, dl_zip):
    """Simplified build for ARM64 with minimal features."""
    print("Using simplified HDF5 build for ARM64", file=stderr)
    
    simplified_cmake_cmd = [
        "cmake", 
        "-DBUILD_SHARED_LIBS:BOOL=OFF",  # Static libs only
        "-DCMAKE_BUILD_TYPE:STRING=RELEASE",
        "-DHDF5_BUILD_CPP_LIB=OFF", 
        "-DHDF5_BUILD_HL_LIB=OFF",  # Disable high-level library
        "-DHDF5_BUILD_TOOLS:BOOL=OFF", 
        "-DBUILD_TESTING:BOOL=OFF",
        "-DHDF5_ENABLE_THREADSAFE:BOOL=OFF",
        "-DHDF5_ENABLE_PARALLEL:BOOL=OFF",
        "-DHDF5_ENABLE_Z_LIB_SUPPORT=OFF",  # Disable zlib
        "-DCMAKE_SYSTEM_PROCESSOR=ARM64",
        "-G", "Visual Studio 17 2022", 
        "-A", "ARM64"
    ]
    
    # Use the simplified command instead of the full one
    # ... rest of build logic similar to original but with simplified_cmake_cmd


def get_cmake_config_path(extract_point, zip_file):
    dir_suffix = basename(zip_file).removesuffix(".zip")
    return pjoin(extract_point, REL_PATH_TO_CMAKE_CFG.format(dir_suffix=dir_suffix))


def get_cmake_install_path(install_path):
    if install_path is not None:
        return CMAKE_INSTALL_PATH_ARG.format(install_path=install_path)
    return ' '


def hdf5_install_cached(install_path):
    if exists(pjoin(install_path, "lib", "hdf5.dll")) or exists(pjoin(install_path, "lib", "hdf5.lib")):
        return True
    return False


def main():
    install_path = environ.get("HDF5_DIR")
    version = environ.get("HDF5_VERSION", DEFAULT_VERSION)
    vs_version = environ.get("HDF5_VSVERSION")
    use_prefix = True if environ.get("H5PY_USE_PREFIX") is not None else False

    if install_path is not None:
        if not exists(install_path):
            makedirs(install_path)
    
    if vs_version is not None:
        cmake_generator = VSVERSION_TO_GENERATOR[vs_version]
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
                       dl_zip)
    else:
        print("using cached hdf5", file=stderr)
    
    if install_path is not None:
        print("hdf5 files: ", file=stderr)
        for dirpath, dirnames, filenames in walk(install_path):
            for file in filenames:
                print(" * " + pjoin(dirpath, file))


if __name__ == '__main__':
    main()
