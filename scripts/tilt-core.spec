# PyInstaller spec for the Tilt core.
#
# A spec rather than a command line because two of the settings below are not
# guesses — they are the two things that were actually missing when the frozen
# build first failed, and a comment beside each is the only way that knowledge
# survives.
#
# Built by scripts/build-sidecar.sh; not meant to be run directly.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 — PyInstaller injects SPECPATH

hidden = [
    # uvicorn resolves its protocol and lifespan implementations by importing
    # them from strings at runtime, so static analysis never sees them.
    *collect_submodules("uvicorn"),
    # Pydantic-settings reaches for dotenv only when a .env exists — which it
    # will not on the build machine, and might on someone's Mac.
    "dotenv",
    # keyring resolves its backend by walking entry points at runtime, so the
    # macOS one is invisible to static analysis and the frozen build would fall
    # back to storing the API key in a file — silently, and only on the machines
    # that actually ship.
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "core" / "tilt" / "__main__.py")],
    pathex=[str(ROOT / "core")],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # The service is headless. Excluding the GUI and science stacks keeps the
    # bundle to what actually runs, which is most of the cold-start budget.
    excludes=["tkinter", "test", "unittest", "pydoc_data", "matplotlib", "numpy", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tilt-core",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

# --onedir, not --onefile: onefile unpacks the whole bundle to a temporary
# directory on every launch, and that cost lands squarely in the time between
# double-clicking Tilt and seeing the journal.
COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="tilt-core",
)
