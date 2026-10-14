"""Experimental Pico 4 Pro Magisk package for QuestLHSync (Android 10, arm64).

Requires Windows: Python 3, JDK javac/jar, Android SDK android.jar + d8 and Android NDK.
Builds the same lhsyncd network service as upstream; PicoFrameReader accesses K0 rings read-only.
This P1 build emits camera F records but DOES NOT yet include Pico factory calibration,
so the Windows solver must not be used for live corrections until P2 is implemented.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "pico"
OUT = ROOT / "out"
BUILD = HERE / "build"


def run(args):
    print("+", " ".join(str(v) for v in args), flush=True)
    subprocess.run([str(v) for v in args], check=True)


def sdk_path():
    return Path(os.environ.get("ANDROID_HOME") or
                os.environ.get("ANDROID_SDK_ROOT") or
                (Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"))


def newest(d, target):
    found = list(d.glob(target))
    if not found:
        raise RuntimeError(f"Cannot find {target} under {d}")
    def version(path):
        part = path.parent.name
        return tuple(int(x) for x in re.findall(r"\d+", part))
    return max(found, key=version)


def clang_executable(sdk):
    env_ndk = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")
    ndk = Path(env_ndk) if env_ndk else None
    if ndk is None or not ndk.is_dir():
        candidates = [p for p in (sdk / "ndk").glob("*") if p.is_dir()]
        if not candidates:
            raise RuntimeError("Android NDK missing: set ANDROID_NDK_HOME")
        ndk = max(candidates, key=lambda p: tuple(map(int, re.findall(r"\d+", p.name))))
    sub = "windows-x86_64" if sys.platform == "win32" else "linux-x86_64"
    exe = ndk / "toolchains" / "llvm" / "prebuilt" / sub / "bin" / ("clang.exe" if sys.platform == "win32" else "clang")
    if not exe.is_file():
        raise RuntimeError(f"NDK clang not found: {exe}")
    return exe


def build():
    OUT.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    sdk = sdk_path()
    clang = clang_executable(sdk)
    flags = [clang, "--target=aarch64-linux-android29", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-fPIE", "-pie"]
    version_text = (ROOT / "src/common/qlhs_status.h").read_text(encoding="utf-8")
    version = re.search(r'#define QLHS_RELEASE "([^"]+)"', version_text).group(1)
    inc = ["-I", ROOT / "src/headset"]
    daemon = BUILD / "lhsyncd"
    sight = BUILD / "pico_lhsight"
    run(flags + [f'-DMODULE_VERSION="v{version}-pico-p1"'] + inc +
        [ROOT / "src/headset/lhsyncd.c", HERE / "src/pico.c", "-llog", "-o", daemon])
    run(flags + [HERE / "src/lhsight_pico.c", "-o", sight])
    android_jar = newest(sdk / "platforms", "*/android.jar")
    d8 = newest(sdk / "build-tools", "*/d8.bat" if sys.platform == "win32" else "*/d8")
    classes = BUILD / "classes"
    dex = BUILD / "dex"
    for folder in (classes, dex):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir()
    run(["javac", "-source", "8", "-target", "8", "-cp", android_jar,
         "-d", classes, HERE / "src/PicoFrameReader.java"])
    classes_jar = BUILD / "PicoFrameReader-classes.jar"
    run(["jar", "cf", classes_jar, "-C", classes, "."])
    run([d8, "--min-api", "29", "--output", dex, classes_jar])
    dex_file = dex / "classes.dex"
    if not dex_file.exists():
        raise RuntimeError("d8 produced no classes.dex")
    reader_jar = BUILD / "PicoFrameReader.jar"
    run(["jar", "cf", reader_jar, "-C", dex, "classes.dex"])

    path = OUT / f"QuestLHSync-pico-module-{version}-p1.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        def add(arc, content, executable=False):
            info = zipfile.ZipInfo(arc, (2026, 10, 14, 0, 0, 0))
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content)
        upstream = ROOT / "magisk/module"
        for rel in ("META-INF/com/google/android/update-binary", "META-INF/com/google/android/updater-script"):
            add(rel, (upstream / rel).read_bytes(), rel.endswith("update-binary"))
        for name in ("service.sh", "customize.sh", "uninstall.sh"):
            add(name, (HERE / "module" / name).read_bytes(), True)
        prop = (HERE / "module/module.prop.in").read_text(encoding="utf-8")
        prop = prop.replace("@VERSION@", f"{version}-pico-p1")
        add("module.prop", prop.encode("utf-8"))
        add("lhsyncd", daemon.read_bytes(), True)
        add("pico_lhsight", sight.read_bytes(), True)
        add("PicoFrameReader.jar", reader_jar.read_bytes())
    print(f"Built {path} ({path.stat().st_size / 1e6:.2f} MB)")
    print("P1 ONLY: Calibrated PC synchronization and tracking corrections are NOT ready.")


if __name__ == "__main__":
    build()
