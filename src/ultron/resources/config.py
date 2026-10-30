"""Per-user resource scope and platform data paths."""
import json
import os
from pathlib import Path
import sys
from .catalog import PathPolicy, ResourceCatalog, ResourceError
from .service import ResourceService


def data_directory():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'ULTRON'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'ULTRON'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'ultron'


def default_roots():
    roots = [Path.home()]
    if sys.platform == 'win32':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetLogicalDrives.restype = ctypes.c_uint32
        kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel.GetDriveTypeW.restype = ctypes.c_uint
        mask = kernel.GetLogicalDrives()
        roots += [Path(f'{chr(65 + index)}:\\') for index in range(26)
                  if mask & (1 << index) and kernel.GetDriveTypeW(f'{chr(65 + index)}:\\') in {2, 3}]
    elif sys.platform == 'darwin':
        roots += [Path('/Applications')]
        volumes = Path('/Volumes')
        if volumes.is_dir():
            roots += [path for path in volumes.iterdir() if path.is_dir() and not path.is_symlink()]
    return list(dict.fromkeys(roots))


def create_service():
    directory = data_directory()
    config_path = Path(os.environ.get('ULTRON_RESOURCE_CONFIG', directory / 'resource-settings.json'))
    config = json.loads(config_path.read_text()) if config_path.is_file() else {}
    if not isinstance(config, dict):
        raise ResourceError('Resource configuration must be a JSON object.')
    for key in ('roots', 'protected'):
        if key in config and (not isinstance(config[key], list) or any(not isinstance(path, str) or not Path(path).expanduser().is_absolute() for path in config[key])):
            raise ResourceError(f"Configuration '{key}' must be a list of absolute paths.")
    roots = config['roots'] if 'roots' in config else default_roots()
    home = Path.home()
    protected = [home / '.ssh', home / '.gnupg', home / '.aws', home / '.azure', home / '.kube',
                 home / 'AppData' / 'Local' / 'Microsoft' / 'Credentials',
                 home / 'AppData' / 'Local' / 'Microsoft' / 'Vault',
                 home / 'AppData' / 'Roaming' / 'Microsoft' / 'Protect',
                 home / 'Library' / 'Keychains']
    if sys.platform == 'win32':
        protected += [Path(os.environ.get('SystemRoot', r'C:\Windows'))]
    elif sys.platform == 'darwin':
        protected += [Path('/System'), Path('/private'), Path('/dev'), Path('/Library/Keychains')]
    protected += [Path(value) for value in config.get('protected', [])]
    return ResourceService(ResourceCatalog(directory / 'resources.sqlite3', PathPolicy(roots, protected)))
