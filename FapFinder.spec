# Native Windows one-folder build; Python, Qt and CUDA inference are bundled.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

hidden = [
    'transformers.models.siglip.configuration_siglip',
    'transformers.models.siglip.modeling_siglip',
    'transformers.models.siglip.processing_siglip',
    'transformers.models.siglip.image_processing_siglip',
    'transformers.models.siglip.tokenization_siglip',
    'transformers.models.auto.modeling_auto',
    'transformers.models.auto.processing_auto',
    'transformers.models.auto.image_processing_auto',
    'transformers.models.auto.tokenization_auto',
    'transformers.models.auto.configuration_auto',
    'transformers.generation',
    'sentencepiece',
]
datas = [('assets/app.ico', 'assets'), ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.')]
datas += collect_data_files('transformers')
datas += copy_metadata('torch')

a = Analysis(['run.py'], pathex=[], binaries=[], datas=datas, hiddenimports=hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['pytest', 'matplotlib', 'scipy', 'pandas', 'IPython', 'tkinter', 'torchaudio', 'torchvision', 'tensorboard', 'cv2'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FapFinder', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    disable_windowed_traceback=False, icon='assets/app.ico')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FapFinder')
