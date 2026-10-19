"""Persistent settings. Secrets are stored only through Windows DPAPI."""
from __future__ import annotations
import base64
import ctypes
import dataclasses
import json
import os
import re
import threading
from pathlib import Path

APP_NAME = '听课稿'
APP_ID = 'LectureInk'
VERSION = '0.2.0'

SOURCE_LANGUAGES = [('auto', '自动识别'), ('en', 'English'), ('zh', '中文'), ('ja', '日本語'), ('ko', '한국어'),
                    ('fr', 'Français'), ('de', 'Deutsch'), ('es', 'Español')]


@dataclasses.dataclass
class Settings:
    mode: str = 'local'                 # 'local' (Moonshine + Google) | 'soniox'
    source_kind: str = 'system'         # 'system' | 'microphone'
    device_name: str = ''
    microphone_name: str = ''
    topic: str = ''
    glossary: str = ''
    source_language: str = 'en'         # API mode hint; basic mode is English only
    remember_key: bool = True
    protected_soniox_key: str = ''
    view: str = 'both'                  # 'both' | 'target' | 'source'
    font_size: int = 17
    follow_latest: bool = True
    save_audio: bool = False
    overlay_enabled: bool = False
    overlay_locked: bool = False
    overlay_show_source: bool = True
    overlay_font_size: int = 26
    overlay_lines: int = 2
    overlay_opacity: float = 0.78
    overlay_geometry: list = dataclasses.field(default_factory=list)


def app_data() -> Path:
    path = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f'.{threading.get_ident()}.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def protect_secret(value: str, decrypt: bool = False) -> str:
    """Windows DPAPI, bound to the current Windows user."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_byte))]
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw, len(raw))
    src = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    dst = Blob()
    crypt = ctypes.windll.crypt32
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(src), APP_ID, None, None, None, 1, ctypes.byref(dst))
    if not ok:
        raise OSError('无法使用 Windows 加密保存密钥')
    try:
        output = ctypes.string_at(dst.data, dst.size)
        return output.decode('utf-8') if decrypt else base64.b64encode(output).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(dst.data, ctypes.c_void_p))


def load_settings(path: Path | None = None) -> Settings:
    path = path or app_data() / 'settings.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        names = {f.name for f in dataclasses.fields(Settings)}
        return Settings(**{k: v for k, v in data.items() if k in names})
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    atomic_json(path or app_data() / 'settings.json', dataclasses.asdict(settings))


def load_soniox_key(settings: Settings) -> str:
    if os.environ.get('SONIOX_API_KEY'):
        return os.environ['SONIOX_API_KEY'].strip()
    if settings.protected_soniox_key:
        try:
            return protect_secret(settings.protected_soniox_key, True)
        except (OSError, ValueError):
            return ''
    return ''


def looks_like_api_key(key: str) -> bool:
    """A pasted paragraph or a mis-copied line should not be saved as a key."""
    return 16 <= len(key) <= 200 and key.isascii() and not re.search(r'\s', key)


def store_soniox_key(settings: Settings, key: str) -> None:
    settings.protected_soniox_key = protect_secret(key) if key and settings.remember_key else ''


def parse_glossary(text: str) -> list[tuple[str, str]]:
    """One entry per line: `source = 译文`, `source -> 译文`, or a bare term."""
    entries = []
    for line in text.splitlines():
        line = line.strip().strip('，,;；')
        if not line or line.startswith('#'):
            continue
        parts = re.split(r'\s*(?:=|＝|->|→|=>)\s*', line, maxsplit=1)
        source = parts[0].strip()
        target = parts[1].strip() if len(parts) > 1 else ''
        if source:
            entries.append((source, target))
    return entries
