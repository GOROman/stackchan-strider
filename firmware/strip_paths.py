"""バイナリに埋め込まれるソースのパス(__FILE__ など)から、ビルドしたパソコンのフォルダ名を消す。

PlatformIO のビルド前に読み込まれる(platformio.ini の extra_scripts)。
パッケージ置き場とプロジェクトのフォルダを、短い名前に置き換えるようコンパイラへ指示する。
Windows では同じフォルダが \\ 区切りと / 区切りの両方で渡されるので、両方を指定する。
"""
import os

Import("env")  # noqa: F821  PlatformIO が用意する

packages = env.subst("$PROJECT_PACKAGES_DIR")  # noqa: F821
project = env.subst("$PROJECT_DIR")  # noqa: F821
home = os.path.expanduser("~")
flags = []
for folder, name in ((packages, "pio-packages"), (project, "."), (home, "home")):
    for variant in {folder, folder.replace("\\", "/"), folder.replace("/", "\\")}:
        flags.append(f"-ffile-prefix-map={variant}={name}")
        flags.append(f"-fmacro-prefix-map={variant}={name}")
for target in (env, DefaultEnvironment()):  # noqa: F821
    target.Append(CCFLAGS=flags)
