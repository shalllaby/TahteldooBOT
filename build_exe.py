import PyInstaller.__main__
import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VERSION = "3.0.0"
APP_NAME = "TahtElDooPublisher"

print("=" * 60)
print("  Building: {} v{}".format(APP_NAME, VERSION))
print("=" * 60)

# 1. Kill running instances
print("[1] Closing any running instances...")
try:
    subprocess.run(["taskkill", "/F", "/IM", "{}.exe".format(APP_NAME)], capture_output=True)
except Exception:
    pass

# 2. Clean old dist
dist_dir = BASE_DIR / "dist" / APP_NAME
if dist_dir.exists():
    print("[2] Cleaning old build files...")
    shutil.rmtree(dist_dir, ignore_errors=True)

# 3. Remove stale pathlib backport
try:
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "pathlib"], capture_output=True)
except Exception:
    pass

# 4. Version info file
version_file = BASE_DIR / "build_version.txt"
v = VERSION.replace(".", ", ") + ", 0"
version_info_content = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v}),
    prodvers=({v}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'0409040B',
        [StringStruct(u'CompanyName', u'Taht El Doo News'),
         StringStruct(u'FileDescription', u'Taht El Doo - Smart News Publisher'),
         StringStruct(u'FileVersion', u'{VERSION}'),
         StringStruct(u'InternalName', u'{APP_NAME}'),
         StringStruct(u'LegalCopyright', u'2026 Taht El Doo News'),
         StringStruct(u'OriginalFilename', u'{APP_NAME}.exe'),
         StringStruct(u'ProductName', u'Taht El Doo Publisher'),
         StringStruct(u'ProductVersion', u'{VERSION}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""".format(v=v, VERSION=VERSION, APP_NAME=APP_NAME)

version_file.write_text(version_info_content, encoding="utf-8")
print("[3] Version info file created for v{}".format(VERSION))

# 5. Data files
icon_file = BASE_DIR / "ico.ico"

add_data_args = [
    "--add-data={};assets".format(BASE_DIR / "assets"),
    "--add-data={};services".format(BASE_DIR / "services" / "article_examples.json"),
    "--add-data={};.".format(BASE_DIR / "press_news_reference_examples.json"),
    "--add-data={};.".format(icon_file),
]

optional_files = [".env", "credentials.json", "token.pickle"]
for fname in optional_files:
    fpath = BASE_DIR / fname
    if fpath.exists():
        add_data_args.append("--add-data={};.".format(fpath))

# 6. Excludes to reduce size
excludes = [
    "tkinter", "unittest", "http.server",
    "xmlrpc", "doctest", "pdb", "lib2to3",
    "numpy", "pandas", "matplotlib", "scipy",
    "IPython", "jupyter", "PyQt5", "PyQt6",
    "test", "tests", "testing", "_pytest", "pytest",
]
exclude_args = ["--exclude-module={}".format(m) for m in excludes]

# 7. Run PyInstaller
args = [
    str(BASE_DIR / "app.py"),
    "--name={}".format(APP_NAME),
    "--windowed",
    "--onedir",
    "--noconfirm",
    "--clean",
    "--collect-all=flet",
    "--icon={}".format(icon_file),
    "--version-file={}".format(version_file),
    *add_data_args,
    *exclude_args,
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    "--hidden-import=PIL.ImageGrab",
    "--hidden-import=googleapiclient.discovery",
    "--hidden-import=google_auth_oauthlib.flow",
    "--hidden-import=google.auth.transport.requests",
    "--hidden-import=requests",
    "--hidden-import=sqlite3",
    "--hidden-import=groq",
    "--hidden-import=openai",
    "--hidden-import=pygame",
]

args = [a for a in args if a]

print("[4] Running PyInstaller (this takes 10-30 minutes)...")
print("-" * 60)
PyInstaller.__main__.run(args)

# 8. Cleanup temp file
try:
    version_file.unlink()
except Exception:
    pass

# 9. Write README
readme = (
    "TahtElDooPublisher v{}\n"
    "================================\n"
    "Run TahtElDooPublisher.exe to start.\n"
    "No Python installation required.\n"
    "\nSupport: https://www.tahteldoo.com/\n"
).format(VERSION)
try:
    (dist_dir / "README.txt").write_text(readme, encoding="utf-8")
except Exception:
    pass

print("\n" + "=" * 60)
print("  BUILD COMPLETE!  v{}".format(VERSION))
print("  Location: {}".format(dist_dir))
print("=" * 60)
