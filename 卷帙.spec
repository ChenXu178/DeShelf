# -*- mode: python ; coding: utf-8 -*-
"""卷帙 DeShelf 打包配置。

封面渲染要 PIL，而 PIL 会把 numpy（连带 19 MB 的 OpenBLAS）和 AVIF 编解码器
（7.5 MB）一起拖进来 —— 这两个都用不到，排除后 EXE 从 30 MB 回到 17 MB 左右。
"""
from PyInstaller.building.datastruct import TOC

# 名字里命中这些就丢掉（只用 JPEG/PNG，不做科学计算）。
# PIL.imagetk 留着：主题缩略图靠它把 Pillow 图直接交给 Tk，保住就省掉
# 一层 PNG 编解码（丢了也能用，只是慢一点）。
_DROP = ("openblas", "numpy", "scipy", "pandas", "matplotlib",
         "_avif", "PIL.imageqt", "PIL.imageshow")


def _keep(entry):
    name = str(entry[0]).lower()
    return not any(k in name for k in _DROP)


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
    excludes=['numpy', 'scipy', 'pandas', 'matplotlib'],
    noarchive=False,
    optimize=0,
)

a.binaries = TOC([b for b in a.binaries if _keep(b)])
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
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
