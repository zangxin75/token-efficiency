# PyInstaller hook for keyring（★ H1 修复）。
# keyring 的后端通过 importlib.metadata entry_points 动态发现，
# PyInstaller 默认不收集这些元数据，打包后 keyrings.alt 兜底后端无法注册。
# 此 hook 显式收集 keyring + keyrings.alt 的元数据和后端入口。

from PyInstaller.utils.hooks import collect_entry_point, copy_metadata

# 收集包元数据（entry_points 注册表所在）
datas = copy_metadata('keyring')
datas += copy_metadata('keyrings.alt')

# 收集所有 keyring.backends entry_points 对应的模块
_, hiddenimports = collect_entry_point('keyring.backends')

# 显式兜底：确保文件后端一定被打入（headless/无桌面环境依赖它）
hiddenimports += [
    'keyrings.alt',
    'keyrings.alt.file',
    'keyring.backends',
    'keyring.backends.Windows',
    'keyring.backends.SecretService',
    'keyring.backends.chainer',
    'keyring.backends.fail',
]
