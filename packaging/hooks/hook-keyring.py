# PyInstaller hook for keyring (H1 fix).
# keyring discovers its backends dynamically via importlib.metadata entry_points.
# PyInstaller does not collect this metadata by default, so after packaging the
# keyrings.alt fallback backend fails to register.
# This hook explicitly collects the metadata and backend entry points for keyring + keyrings.alt.

from PyInstaller.utils.hooks import collect_entry_point, copy_metadata

# Collect package metadata (where the entry_points registry lives)
datas = copy_metadata('keyring')
datas += copy_metadata('keyrings.alt')

# Collect modules for all keyring.backends entry_points
_, hiddenimports = collect_entry_point('keyring.backends')

# Explicit fallback: ensure the file backend is always bundled (required in headless / no-desktop environments)
hiddenimports += [
    'keyrings.alt',
    'keyrings.alt.file',
    'keyring.backends',
    'keyring.backends.Windows',
    'keyring.backends.SecretService',
    'keyring.backends.chainer',
    'keyring.backends.fail',
]
