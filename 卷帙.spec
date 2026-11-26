# -*- mode: python ; coding: utf-8 -*-
"""卷帙 DeShelf 打包配置。

封面渲染要 PIL，而 PIL 会把 numpy（连带 19 MB 的 OpenBLAS）和 AVIF 编解码器
（7.5 MB）一起拖进来 —— 这两个都用不到，排除后 EXE 从 30 MB 回到 17 MB 左右。
"""
from PyInstaller.building.datastruct import TOC

# 名字里命中这些就丢掉（只用 JPEG/PNG，不做科学计算）。
# 这里只管二进制和数据文件；纯 Python 模块（PIL.ImageQt 之类）必须写进
# 下面的 excludes，名字过滤对 PYZ 里的模块不生效。
# PIL.imagetk 留着：主题缩略图靠它把 Pillow 图直接交给 Tk，保住就省掉
# 一层 PNG 编解码（丢了也能用，只是慢一点）。
_DROP = ("openblas", "numpy", "scipy", "pandas", "matplotlib", "_avif")


# 系统自带的 CRT：Win10+ 由操作系统提供，不该打进 EXE。原先这些是从
# D:\SDK\OpenJDK\11\bin 误抓进来的（JDK 的 bin 排在 System32 前面）。
_SYSTEM_DLL = ("api-ms-win-", "ucrtbase.dll")


def _keep(entry):
    name = str(entry[0]).lower()
    return not any(k in name for k in _DROP)


def _keep_binary(entry):
    """_DROP 与系统 DLL 两条规则必须同时生效，缺一条就会漏东西。"""
    return _keep(entry) and not str(entry[0]).lower().startswith(_SYSTEM_DLL)


a = Analysis(
    ['Juanzhi_Desktop.py'],
    pathex=[],
    binaries=[],
    # 版面主题是纯数据：打包进 EXE；用户也可在 EXE 同级放 styles 覆盖
    datas=[('styles', 'styles')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 纯 Python 模块只能靠 excludes 摘掉（名字要跟文件名一致，大小写敏感）。
    # PIL.ImageQt：只在 Image.py 的 `if TYPE_CHECKING:`（恒为 False）里出现过，
    #   运行时永远不执行，但 modulegraph 仍会把它当静态导入收进来。
    # PIL.ImageShow：只在 Image.show() 里懒导入，本程序不与系统看图器交互。
    # setuptools 一族：html2image 的 chrome_cdp 会 import requests → urllib3，
    # 而 urllib3 里那段 `from backports import zstd` 被 modulegraph 认成了
    # setuptools 自带的 vendored 包，于是整棵 setuptools（含 packaging、
    # distutils、pydoc、_pyrepl、site）被拖进来。3.15 上 urllib3 实际走
    # `from compression import zstd` 分支，且两处都用 try/except ImportError
    # 包着，backports 在运行期根本不会被执行 —— 摘掉它们不影响 html2image。
    excludes=['numpy', 'scipy', 'pandas', 'matplotlib',
              'PIL.ImageQt', 'PIL.ImageShow',
              'setuptools', 'pkg_resources', '_distutils_hack', 'distutils',
              'packaging', 'pydoc', 'pydoc_data', '_pyrepl', 'site',
              '_sitebuiltins'],
    noarchive=False,
    optimize=2,
)

a.binaries = TOC([b for b in a.binaries if _keep_binary(b)])
a.datas = TOC([d for d in a.datas if _keep(d)])

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='卷帙',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['_uuid.pyd'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
