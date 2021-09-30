#!/usr/bin/env python3

import glob, re, os, os.path, shutil, string, sys, argparse, traceback, multiprocessing
from subprocess import check_call, check_output, CalledProcessError

IPHONEOS_DEPLOYMENT_TARGET='13.0'  # default, can be changed via command line options or environemnt variable

JANSSON_EXTRA_CMAKE_FLAGS = [
    "-DJANSSON_WITHOUT_TESTS=ON",
    "-DJANSSON_EXAMPLES=OFF",
    "-DJANSSON_BUILD_DOCS=OFF"
]

def execute(cmd, cwd = None):
    print("Executing: %s in %s" % (cmd, cwd), file=sys.stderr)
    print('Executing: ' + ' '.join(cmd))
    retcode = check_call(cmd, cwd=cwd)
    if retcode != 0:
        raise Exception("Child returned:", retcode)

class Builder:
    def __init__(self, configuration, bitcode_enabled, deployment_target):
        self.configuration = configuration
        self.bitcode_enabled = bitcode_enabled
        self.deployment_target = deployment_target

    def get_path_relative_to_script(self, *path_components):
        script_dir_path = os.path.abspath(os.path.dirname(__file__))
        return os.path.join(script_dir_path, *path_components)

    def get_toolchain(self):
        return self.get_path_relative_to_script("ios-cmake", "ios.toolchain.cmake")

    def get_platforms(self):
        return ["SIMULATOR64", "OS64"]

    def _build(self, out_dir, root_dir, lib_name, extra_cmake_flags):
        out_dir = os.path.abspath(out_dir)
        root_dir = self.get_path_relative_to_script(root_dir)
        os.makedirs(out_dir, exist_ok=True)
        build_path = os.path.join(out_dir, lib_name, "build")

        for platform in self.get_platforms():
            platform_build_dir = os.path.join(build_path, platform)
            os.makedirs(platform_build_dir, exist_ok=True)
            print("Creating directory " + platform_build_dir)
            platform_install_dir = os.path.join(out_dir, platform)
            self.build_platform(platform, platform_build_dir, platform_install_dir, root_dir, extra_cmake_flags)

    def merge_libs(self, out_dir, lib_name):
        out_dir = os.path.abspath(out_dir)
        platform_libs_path = os.path.join(out_dir, "intermediate")
        os.makedirs(platform_libs_path, exist_ok=True)

        platforms = self.get_platforms()

        for platform in platforms:
            platform_install_dir = self.platform_install_dir(out_dir, platform)
            platform_merged_lib_file = os.path.join(platform_libs_path, self.platform_lib_file(lib_name, platform))
            platform_lib_dir = os.path.join(platform_install_dir, "lib")
            self.merge_libs_in_directory(platform_lib_dir, platform_merged_lib_file)

        framework_path = os.path.join(out_dir, f"{lib_name}.framework")
        framework_include_path = os.path.join(framework_path, "include")
        os.makedirs(final_lib_path, exist_ok=True)
        os.makedirs(final_include_path, exist_ok=True)

        self.create_universal_static_lib(platform_libs_path, os.path.join(framework_path, lib_name))
        platform_include_dir = os.path.join(self.platform_install_dir(out_dir, platforms[0]), "include")
        shutil.copytree(platform_include_dir, framework_include_path, dirs_exist_ok=True)

    def platform_install_dir(self, out_dir, platform):
        return os.path.join(out_dir, platform)


    def platform_lib_file(self, lib_name, platform):
        return f"{lib_name}_{platform}.a"

    def build(self, out_dir, root_dir, lib_name, extra_cmake_flags = None):
        if extra_cmake_flags is None:
            extra_cmake_flags = []
        try:
            self._build(out_dir, root_dir, lib_name, extra_cmake_flags)
        except Exception as e:
            print("="*60, file=sys.stderr)
            print("ERROR: %s" % e, file=sys.stderr)
            print("="*60, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

    def get_cmake_xcode_generate_command(self, platform, install_dir, root_dir, extra_flags):
        return [
            "cmake",
            root_dir,
            "-GXcode",
            f"-DCMAKE_TOOLCHAIN_FILE={self.get_toolchain()}",
            f"-DPLATFORM={platform}",
            "-DCMAKE_XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY=''",
            "-DCMAKE_XCODE_ATTRIBUTE_DEVELOPMENT_TEAM=''",
            "-DBUILD_SHARED_LIBS=OFF",
            f"-DDEPLOYMENT_TARGET={self.deployment_target}",
            f"-DENABLE_BITCODE={'ON' if self.bitcode_enabled else 'OFF'}",
            f"-DCMAKE_INSTALL_PREFIX={install_dir}",
        ] + extra_flags

    def get_cmake_build_command(self):
        args = [
            "cmake",
            "--build",
            ".",
            "--clean-first",
            "--config",
            self.configuration,
            "--target",
            "install",
        ]
        return args

    def build_platform(self, platform, build_dir, install_dir, root_dir, extra_cmake_flags):
        os.environ["PKG_CONFIG_PATH"] = os.path.join(install_dir, "lib", "pkgconfig")
        execute(self.get_cmake_xcode_generate_command(platform, install_dir, root_dir, extra_cmake_flags), cwd=build_dir)
        execute(self.get_cmake_build_command(), cwd=build_dir)

    def merge_libs_in_directory(self, directory_path, out_lib_file_path):
        print("Merging libraries in path " + directory_path)
        libs = glob.glob(os.path.join(directory_path, "*.a"))
        print("Merging libraries:\n\t%s" % "\n\t".join(libs), file=sys.stderr)
        execute(["libtool", "-static", "-o", out_lib_file_path] + libs)

    def create_universal_static_lib(self, directory_path, out_lib_file_path):
        libs = glob.glob(os.path.join(directory_path, "*.a"))
        lipocmd = ["lipo", "-create"]
        lipocmd.extend(libs)
        lipocmd.extend(["-o", out_lib_file_path])
        print("Creating universal library from:\n\t%s" % "\n\t".join(libs), file=sys.stderr)
        execute(lipocmd)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='The script builds Avro static lib for iOS.')
    parser.add_argument('out_dir', help='folder to put built library')
    parser.add_argument('--configuration', dest='configuration', choices=["Debug", "Release"], required=True, help='Configuration to build')
    parser.add_argument('--enable-bitcode', default=False, dest='bitcode_enabled', action='store_true', help='enable bitcode (disabled by default)')
    parser.add_argument('--deployment_target', default=IPHONEOS_DEPLOYMENT_TARGET, dest='deployment_target',help='Deployment target')
    args = parser.parse_args()
    b = Builder(args.configuration, args.bitcode_enabled, args.deployment_target)
    b.build(args.out_dir, "jansson", "jansson", JANSSON_EXTRA_CMAKE_FLAGS)
    b.build(args.out_dir, os.path.join("lang", "c"), "avro")
    b.merge_libs(args.out_dir, "avro")
