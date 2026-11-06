# PyInstaller: pyinstaller TibbiDikte.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
for pkg in ("sherpa_onnx", "damga"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
datas += collect_data_files("sounddevice")
datas += [
    ("app/medical/lexicon_tr.txt", "app/medical"),
    ("app/medical/corrections_tr.tsv", "app/medical"),
    ("app/medical/radiology_terms_tr.txt", "app/medical"),
    ("app/medical/radiology_known_tr.txt", "app/medical"),
    ("app/medical/collect_sentences_tr.txt", "app/medical"),
    ("app/medical/general_tr_words.txt", "app/medical"),
    ("app/licensing/public_key.pem", "app/licensing"),
    ("app/silero_vad.onnx", "app"),
    ("app/icons/*.svg", "app/icons"),
    ("app/icons/LICENSE", "app/icons"),
]
hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32", "PySide6.QtSvg"]

a = Analysis(["run.py"], pathex=["."], datas=datas, binaries=binaries, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
                       "PySide6.QtQuick", "PySide6.QtQml"])

# Boyut: damga'nın yalnızca Türkçe ITN grameri, Qt'nin kullanılmayan parçaları çıkarılır
import re
_drop = re.compile(
    r"(damga[\\/](?!tr[\\/]itn|_|[^\\/]+\.py)[a-z]{2}[\\/])"   # tr/itn dışındaki diller
    r"|(damga[\\/]tr[\\/]tn[\\/])"                              # metin normalizasyonu (kullanılmıyor)
    r"|(opengl32sw\.dll)|(Qt6(Quick|Qml|Pdf|VirtualKeyboard|OpenGL)\w*\.dll)"
    r"|(PySide6[\\/]translations[\\/](?!qtbase_tr))",
    re.IGNORECASE)
a.datas = [t for t in a.datas if not _drop.search(t[0])]
a.binaries = [t for t in a.binaries if not _drop.search(t[0])]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TibbiDikte", console=False, upx=False,
          icon="app/icons/logo.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="TibbiDikte", upx=False)
