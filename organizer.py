from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk
from queue import Queue, Empty
from contextlib import contextmanager
import stat as stat_module
import sys
if os.name == 'nt':
    import msvcrt
else:
    import fcntl

def _windows_desktop():
    """Query Known Folder API; never assumes a Desktop basename for redirected folders."""
    import ctypes
    import uuid
    class GUID(ctypes.Structure):
        _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
                    ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]
    folder = GUID.from_buffer_copy(uuid.UUID('B4BFCC3A-DB2C-424C-B029-7FE99A87C641').bytes_le)
    value = ctypes.c_wchar_p()
    function = ctypes.windll.shell32.SHGetKnownFolderPath
    function.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    function.restype = ctypes.c_long
    result = function(ctypes.byref(folder), 0, None, ctypes.byref(value))
    if result != 0:
        raise RuntimeError('Windows 桌面位置查询失败；请显式设置 DESKTOP_ORGANIZER_ROOT')
    try:
        return Path(value.value)
    finally:
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(value, ctypes.c_void_p))


def _posix_desktop(environment=None, home=None):
    """Resolve the XDG desktop without assuming that its name is Desktop."""
    environment = os.environ if environment is None else environment
    home = Path(home or environment.get('HOME') or Path.home()).expanduser()
    config_home = Path(environment.get('XDG_CONFIG_HOME', home / '.config')).expanduser()
    config = config_home / 'user-dirs.dirs'
    if config.is_file():
        for line in config.read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.fullmatch(r'\s*XDG_DESKTOP_DIR\s*=\s*"([^"]+)"\s*', line)
            if match:
                value = match.group(1).replace('$HOME', str(home))
                path = Path(value).expanduser()
                if path.is_absolute() and path.is_dir():
                    return Path(os.path.abspath(path))
                break
    fallback = home / 'Desktop'
    if fallback.is_dir():
        return Path(os.path.abspath(fallback))
    raise RuntimeError('Linux 桌面目录不存在；请显式设置 DESKTOP_ORGANIZER_ROOT')


def get_desktop_path(environment=None):
    environment = os.environ if environment is None else environment
    if 'DESKTOP_ORGANIZER_ROOT' in environment:
        value = environment['DESKTOP_ORGANIZER_ROOT']
        if not value:
            raise RuntimeError('DESKTOP_ORGANIZER_ROOT 不能为空')
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise RuntimeError('DESKTOP_ORGANIZER_ROOT 必须是存在的绝对目录路径')
        return Path(os.path.abspath(path))
    return _windows_desktop() if os.name == 'nt' else _posix_desktop(environment)


def _state_dir(environment=None):
    environment = os.environ if environment is None else environment
    if os.name == 'nt':
        return Path(environment.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'DesktopOrganizer'
    return Path(environment.get('XDG_STATE_HOME', Path.home() / '.local/state')).expanduser() / 'desktop-organizer'


DESKTOP = get_desktop_path()
DESTINATION = DESKTOP
STATE_DIR = _state_dir()
LOG_FILE = STATE_DIR / "last_move.json"
CATEGORIES = {"文档": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".rtf"}, "文本": {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml"}, "网页": {".html", ".htm", ".css", ".js"}, "图片": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff"}, "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}, "视频": {".mp4", ".mov", ".avi", ".mkv", ".webm"}, "音频": {".mp3", ".wav", ".m4a", ".flac", ".aac"}}
SOFTWARE_SUFFIXES = {".exe", ".msi", ".dmg", ".pkg", ".lnk", ".url"}
SKIP_NAMES = {"desktop.ini"}
TEMP_PREFIXES = ("~$",)
PAPER_RULES = {"论文-植物与转运": {"abc transporter": 10, "转运蛋白": 9, "transporter": 6, "arabidopsis": 6, "拟南芥": 6, "植物": 5, "苜蓿": 5, "abcb": 5, "abcc": 5}, "论文-多肽与蛋白": {"peptide": 7, "多肽": 7, "protein engineering": 7, "amino acid": 3, "protein": 1, "蛋白": 1}, "论文-药物与结构": {"structure-based": 7, "结构生物学": 7, "medicinal": 6, "drug": 5, "药物": 5, "ligand": 4, "docking": 4}, "论文-生物信息": {"bioinformatics": 7, "machine learning": 7, "深度学习": 7, "genome": 5, "基因组": 5, "proteomics": 5, "蛋白质组": 5}}
_LOCK = threading.RLock()

@dataclass
class FileRecord:
    source: str
    target: str
    category: str
    confidence: int
    reason: str = ""
    warning: str = ""
    size: int = 0
    mtime_ns: int = 0
    fingerprint: str = ""
    @property
    def source_path(self): return Path(self.source)
    @property
    def target_path(self): return Path(self.target)
Move = FileRecord

def _root_key(root, platform_name=None):
    value = str(root)
    return value.casefold() if (platform_name or os.name) == 'nt' else value


def root_state_dir(root=None):
    root = Path(root or DESKTOP).resolve()
    key = hashlib.sha256(_root_key(root).encode()).hexdigest()[:24]
    return STATE_DIR / key

def _active_log():
    return root_state_dir() / 'last_move.json'


def _log_file():
    active = _active_log()
    if active.exists():
        return active
    history = _reject_links(root_state_dir() / 'history')
    previous = sorted(history.glob('*.json')) if history.is_dir() else []
    return previous[-1] if previous else active


def _history_file(data):
    return _reject_links(root_state_dir() / 'history' / f"{data['created_ns']:020d}-{data['transaction']}.json")


def _archive_current(log, data, root):
    destination = _history_file(data)
    if destination == log:
        return
    if destination.exists():
        if _load_journal(destination, root) != data:
            raise RuntimeError('历史记录冲突，禁止覆盖')
    else:
        atomic_write_json(destination, data)

def full_fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()
quick_fingerprint = full_fingerprint

def atomic_write_json(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def _reject_links(path):
    """Reject symlinks and Windows reparse points before resolving any path."""
    path = _absolute(path)
    for ancestor in reversed((path, *path.parents)):
        try:
            attributes = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat_module.S_ISLNK(attributes.st_mode) or getattr(attributes, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('拒绝符号链接或目录联接路径')
    return path


def _strict_inside(path, root):
    try:
        candidate = _reject_links(path)
        base = _reject_links(root)
        relative = candidate.relative_to(base)
        return bool(relative.parts) and not any(':' in part for part in relative.parts)
    except (ValueError, OSError, RuntimeError):
        return False


def _path_key(path):
    value = str(_absolute(path))
    return value.casefold() if os.name == 'nt' else value


def _rename_no_replace(source, target):
    """Move one regular file without ever replacing an existing target."""
    source, target = os.fspath(source), os.fspath(target)
    if os.name == 'nt':
        os.rename(source, target)
        return
    if not sys.platform.startswith('linux'):
        raise RuntimeError('当前仅支持 Windows 和 Linux 本地文件系统')
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, 'renameat2', None)
    if renameat2 is None:
        raise RuntimeError('当前 Linux C 库缺少原子不覆盖移动支持')
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p,
                          ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)


def _validate_root(root):
    root = _reject_links(root)
    if not root.is_dir():
        raise RuntimeError('整理根目录不存在或不是目录')
    return root


def pdf_text(path):
    try:
        with Path(path).open("rb") as handle:
            if handle.read(5) != b"%PDF-": return "", "文件扩展名为 PDF，但文件头不是 PDF"
        try:
            from pypdf import PdfReader
        except ImportError: return "", "缺少 pypdf，PDF 仅按通用文档保留，未自动分类"
        text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path), strict=False).pages[:2]).lower()
        return text, "" if text.strip() else "PDF 可读取但没有可提取文本"
    except Exception as error: return "", f"PDF 无法读取：{type(error).__name__}"

def paper_category(path):
    text, warning = pdf_text(path)
    if warning:
        category = '论文-待确认' if '文件头不是 PDF' in warning else '文档'
        return category, 0, 'PDF 需人工确认', warning
    hay = f'{path.stem.lower()} {text}'
    scores = {category: sum(weight for key, weight in rules.items() if key in hay)
              for category, rules in PAPER_RULES.items()}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    category, score = ranked[0]
    if score < 4:
        return '文档', 90, '可读取的通用 PDF 文档', ''
    if ranked[1][1] >= score - 2:
        return '论文-待确认', 45, '多个主题规则得分接近', '主题有歧义，请人工确认'
    reason = '规则匹配：' + ','.join(k for k, w in PAPER_RULES[category].items() if k in hay and w >= 4)
    return category, min(98, 45 + score * 5), reason, ''

def category_for(path):
    if path.suffix.lower() == ".pdf": return paper_category(path)
    for category, extensions in CATEGORIES.items():
        if path.suffix.lower() in extensions: return category, 92, f"扩展名 {path.suffix.lower()}", ""
    return "其他", 45, "未匹配已知文件类型", ""

def related_key(path):
    name = path.stem.lower().replace("_", " ").replace("-", " ")
    name = re.sub(r"\s*\((?:copy|副本|\d+)\)$", "", name)
    name = re.sub(r"\s+(?:copy|副本|v?\d+(?:\.\d+)*)$", "", name)
    return re.sub(r"\s+", " ", name).strip()

def unique_target(target):
    if not target.exists(): return target
    for index in range(2, 100000):
        candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
        if not candidate.exists(): return candidate
    raise RuntimeError("无法生成不冲突的目标名")

def scan():
    root = _validate_root(DESKTOP); items = []
    for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        try:
            if item.is_symlink() or not item.is_file() or item.name.lower() in SKIP_NAMES or any(item.name.startswith(x) for x in TEMP_PREFIXES) or item.suffix.lower() in SOFTWARE_SUFFIXES: continue
            items.append(item)
        except OSError: continue
    classified = {item: category_for(item) for item in items}; grouped = {}
    for item, info in classified.items(): grouped.setdefault((info[0], related_key(item)), []).append(item)
    result = []
    for item in items:
        category, confidence, reason, warning = classified[item]; directory = root / category
        if len(grouped[(category, related_key(item))]) > 1 and related_key(item): directory /= related_key(item)[:40]
        try:
            stat = item.stat(); fingerprint = full_fingerprint(item)
            result.append(FileRecord(str(item), str(unique_target(directory / item.name)), category, confidence, reason, warning, stat.st_size, stat.st_mtime_ns, fingerprint))
        except OSError as error: result.append(FileRecord(str(item), str(directory / item.name), category, 0, reason, f"无法读取文件：{type(error).__name__}"))
    return result

def validate_record(record, root=None):
    root = _validate_root(root or DESKTOP); source, target = Path(record.source), Path(record.target)
    if not _strict_inside(source, root) or not _strict_inside(target, root): raise RuntimeError("路径不安全或越界")
    if source.is_symlink() or target.is_symlink() or target.exists(): raise RuntimeError("路径不安全或目标已存在")
    if not source.is_file(): raise RuntimeError(f"源文件不存在：{source.name}")
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns, full_fingerprint(source)) != (record.size, record.mtime_ns, record.fingerprint): raise RuntimeError(f"源文件在扫描后发生变化：{source.name}")

@contextmanager
def _exclusive_lock(path):
    """OS-owned byte lock is released even if this process crashes.

    Keep the lock file permanently: unlinking it can split simultaneous owners.
    """
    path = _reject_links(Path(path).with_suffix('.lock'))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b'0')
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == 'nt':
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as error:
            raise RuntimeError('另一个实例正在整理或撤销，请稍后重试') from error
        yield
    finally:
        if locked:
            if os.name == 'nt':
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _identity(path):
    info = Path(path).stat()
    return [info.st_dev, info.st_ino]


def _matches_entry(path, entry):
    path = Path(path)
    return (path.is_file() and _identity(path) == entry['identity']
            and path.stat().st_size == entry['size']
            and full_fingerprint(path) == entry['fingerprint'])


def _load_journal(log, root):
    _reject_links(log)
    data = json.loads(log.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('version') != 4
            or data.get('root') != str(root)
            or not isinstance(data.get('transaction'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', data['transaction'])
            or not isinstance(data.get('created_ns'), int)
            or data.get('status') not in ('prepared', 'moving', 'committed', 'recovery-required')
            or not isinstance(data.get('moves'), list)):
        raise RuntimeError('旧版、损坏或根目录不匹配的事务记录；已保留，禁止自动处理')
    seen = set()
    for entry in data['moves']:
        if not isinstance(entry, dict):
            raise RuntimeError('事务条目损坏')
        source, target = Path(entry.get('source', '')), Path(entry.get('target', ''))
        identity = entry.get('identity')
        if (not _strict_inside(source, root) or not _strict_inside(target, root)
                or _absolute(source).parent != root or _absolute(target).parent == root
                or entry.get('phase') not in ('pending', 'intent', 'moved', 'undo-intent', 'restored')
                or not isinstance(identity, list) or len(identity) != 2
                or not all(isinstance(v, int) for v in identity)
                or not isinstance(entry.get('size'), int)
                or not re.fullmatch(r'[0-9a-f]{64}', entry.get('fingerprint', ''))):
            raise RuntimeError('事务条目路径、身份或状态不安全')
        for path in (source, target):
            key = _path_key(path)
            if key in seen:
                raise RuntimeError('事务包含重复路径')
            seen.add(key)
    return data


def _persist(log, data):
    atomic_write_json(log, data)


def _recover(log, data, root):
    """Undo/recover one transaction. Every reverse move has durable intent."""
    restored, warnings = 0, []
    for entry in reversed(data['moves']):
        if entry['phase'] == 'restored':
            continue
        source, target = Path(entry['source']), Path(entry['target'])
        try:
            if not _strict_inside(source, root) or not _strict_inside(target, root):
                raise RuntimeError('恢复期间路径变成链接或越界')
            phase = entry['phase']
            source_ok = source.exists() and _matches_entry(source, entry)
            # Pending/intended moves may not have occurred. Never remove a competitor.
            if phase in ('pending', 'intent') and source_ok:
                entry['phase'] = 'restored'
                _persist(log, data)
                continue
            # A previous undo may have died immediately after its rename.
            if phase == 'undo-intent' and source_ok and not target.exists():
                entry['phase'] = 'restored'
                _persist(log, data)
                continue
            if source.exists():
                warnings.append(f'原位置已有文件：{source.name}')
                continue
            if not target.exists() or not _matches_entry(target, entry):
                warnings.append(f'目标缺失、被替换或内容已修改：{target.name}')
                continue
            entry['phase'] = 'undo-intent'
            _persist(log, data)
            # The platform helper is atomic and never replaces a competitor.
            if not _strict_inside(source, root) or not _strict_inside(target, root):
                raise RuntimeError('恢复路径发生变化')
            _rename_no_replace(target, source)
            restored += 1
            entry['phase'] = 'restored'
            _persist(log, data)
        except Exception as error:
            warnings.append(f'{source.name}：恢复中断（{type(error).__name__}）')
            # Stop on a write error: persisted intent is needed for a safe retry.
            break
    remaining = [entry for entry in data['moves'] if entry['phase'] != 'restored']
    if not warnings and not remaining:
        duplicate = _history_file(data)
        if log != duplicate and duplicate.exists():
            archived = _load_journal(duplicate, root)
            if archived['transaction'] != data['transaction']:
                raise RuntimeError('历史记录身份冲突')
            duplicate.unlink()
        log.unlink()
    else:
        data['status'] = 'recovery-required'
        # Persist completed bookkeeping too; if this fails, old intent is recoverable.
        try:
            data['moves'] = remaining
            _persist(log, data)
        except Exception as error:
            warnings.append(f'恢复记录未更新：{type(error).__name__}；请保留状态目录并重试')
    return restored, warnings


def execute(moves):
    with _LOCK:
        if not moves:
            return {'moves': []}
        root, log = _validate_root(DESKTOP), _active_log()
        with _exclusive_lock(log):
            previous_log = _log_file()
            previous = _load_journal(previous_log, root) if previous_log.exists() else None
            if previous and (previous['status'] != 'committed' or any(e['phase'] != 'moved' for e in previous['moves'])):
                raise RuntimeError('上一笔整理尚未恢复完成。请先撤销/恢复，禁止覆盖记录')
            entries = []
            seen = set()
            for move in moves:
                validate_record(move, root)
                if _absolute(move.source).parent != root or _absolute(move.target).parent == root:
                    raise RuntimeError('只允许根目录文件移动到其分类子目录')
                for path in (move.source, move.target):
                    key = _path_key(path)
                    if key in seen:
                        raise RuntimeError('计划包含重复路径')
                    seen.add(key)
                entry = asdict(move)
                entry.update(identity=_identity(move.source), phase='pending')
                entries.append(entry)
            if previous:
                _archive_current(previous_log, previous, root)
            data = {'version': 4, 'transaction': hashlib.sha256(os.urandom(32)).hexdigest(),
                    'created_ns': max(time.time_ns(), previous['created_ns'] + 1 if previous else 0),
                    'root': str(root), 'status': 'prepared', 'moves': entries}
            _persist(log, data)  # If this fails, no file was moved and no fallback overwrites state.
            try:
                for move, entry in zip(moves, entries):
                    validate_record(move, root)
                    if _identity(move.source) != entry['identity']:
                        raise RuntimeError('源文件身份发生变化')
                    Path(move.target).parent.mkdir(parents=True, exist_ok=True)
                    if not _strict_inside(move.target, root):
                        raise RuntimeError('目标目录发生变化')
                    entry['phase'] = 'intent'
                    data['status'] = 'moving'
                    _persist(log, data)
                    _rename_no_replace(move.source, move.target)
                    entry['phase'] = 'moved'
                    _persist(log, data)
                data['status'] = 'committed'
                _persist(log, data)
                return data
            except Exception as error:
                try:
                    _, warnings = _recover(log, _load_journal(log, root), root)
                except Exception as recovery_error:
                    warnings = [f'恢复尚未完成：{type(recovery_error).__name__}']
                state = '已回滚本次移动' if not warnings else '仍有未恢复项目，事务记录已保留，请使用撤销/恢复：' + '；'.join(warnings)
                raise RuntimeError(f'整理失败：{error}。{state}') from error


def undo():
    with _LOCK:
        root = _validate_root(DESKTOP)
        with _exclusive_lock(_active_log()):
            log = _log_file()
            if not log.exists():
                return 0, ['没有可撤销的整理记录']
            data = _load_journal(log, root)  # Validate the entire journal before any move.
            return _recover(log, data, root)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('桌面整理器')
        self.geometry('1050x650')
        self.minsize(820, 500)
        self.records = []
        self.busy = False
        self.queue = Queue()
        self._poll_id = None
        self._build_ui()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.refresh()

    def _build_ui(self):
        ttk.Label(self, text='桌面整理器', font=('Segoe UI', 20, 'bold')).pack(anchor='w', padx=24, pady=(20, 2))
        ttk.Label(self, text=f'安全整理：{DESKTOP}（只处理根目录文件）').pack(anchor='w', padx=24)
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=24, pady=8)
        self.scan_button = ttk.Button(bar, text='重新扫描', command=self.refresh)
        self.organize_button = ttk.Button(bar, text='执行安全项目', command=self.organize)
        self.undo_button = ttk.Button(bar, text='撤销 / 恢复上次整理', command=self.restore)
        for button in (self.scan_button, self.organize_button, self.undo_button):
            button.pack(side='left', padx=(0, 8))
        self.status = ttk.Label(bar)
        self.status.pack(side='right')
        frame = ttk.Frame(self)
        frame.pack(fill='both', expand=True, padx=24, pady=(8, 24))
        self.tree = ttk.Treeview(frame, columns=('target', 'confidence', 'warning'), show='tree headings')
        for column, label, width in [('#0', '文件 / 整理分支', 280), ('target', '将移动到', 340), ('confidence', '规则匹配分', 90), ('warning', '提示', 220)]:
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width)
        vertical = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def _set_busy(self, busy):
        self.busy = busy
        for button in (self.scan_button, self.organize_button, self.undo_button):
            button.configure(state='disabled' if busy else 'normal')

    def _start(self, action, records=None):
        self._action = action
        self._set_busy(True)
        self._thread = threading.Thread(target=self._worker, args=(action, records), daemon=False)
        self._thread.start()
        self._poll_id = self.after(50, self._poll)

    def _poll(self):
        self._poll_id = None
        try:
            kind, value = self.queue.get_nowait()
        except Empty:
            self._poll_id = self.after(50, self._poll)
            return
        self._thread.join()
        self._thread = None
        self._set_busy(False)
        if kind == 'scan':
            self.records = value
            self._render()
        elif kind == 'error':
            self.records = []
            self._render()
            self.status.configure(text='操作未完成，请查看提示并重新扫描或恢复')
            messagebox.showerror('操作失败', str(value))
        elif kind == 'execute':
            messagebox.showinfo('整理完成', f"已整理 {len(value['moves'])} 个文件。撤销记录已保留。")
            self.refresh()
        elif kind == 'undo':
            count, warnings = value
            message = f'已恢复 {count} 个文件。'
            if warnings:
                message += '\n\n未恢复项目：\n' + '\n'.join(warnings)
            (messagebox.showwarning if warnings else messagebox.showinfo)('撤销 / 恢复结果', message)
            self.refresh()

    def refresh(self):
        if self.busy:
            return
        self.records = []
        self._start('scan')

    def _worker(self, action, records):
        try:
            result = scan() if action == 'scan' else execute(records) if action == 'execute' else undo()
            self.queue.put((action, result))
        except Exception as error:
            self.queue.put(('error', str(error)))

    def _render(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        root_node = self.tree.insert('', 'end', text='桌面', values=(str(DESKTOP), '', ''), open=True)
        branches = {}
        for record in self.records:
            relative = Path(record.target).relative_to(_absolute(DESKTOP))
            parent, parts = root_node, []
            for part in relative.parts[:-1]:
                parts.append(part)
                key = tuple(parts)
                if key not in branches:
                    branches[key] = self.tree.insert(parent, 'end', text='📁 ' + part, values=(str(Path(DESKTOP).joinpath(*parts)), '', ''), open=True)
                parent = branches[key]
            self.tree.insert(parent, 'end', text='📄 ' + Path(record.source).name, values=(record.target, str(record.confidence), record.warning or record.reason))
        eligible = sum(r.confidence >= 70 and not r.warning for r in self.records)
        pending = '；存在上次记录，可撤销/恢复' if _log_file().exists() else ''
        self.status.configure(text=f'发现 {len(self.records)} 个；可整理 {eligible} 个{pending}')

    def organize(self):
        if self.busy:
            return
        selected = [r for r in self.records if r.confidence >= 70 and not r.warning]
        if not selected:
            messagebox.showinfo('无需整理', '没有无警告且匹配分达到阈值的项目。')
            return
        if not messagebox.askyesno('确认整理', f'仅执行当前预览中的 {len(selected)} 个项目。低分和异常文件保留原位。确认继续？'):
            return
        self._start('execute', list(selected))

    def restore(self):
        if self.busy or not messagebox.askyesno('确认撤销 / 恢复', '按上次事务记录恢复，并检查文件身份与完整内容。确认继续？'):
            return
        self._start('undo')

    def _on_close(self):
        if self.busy:
            messagebox.showinfo('正在处理', '请等待当前操作完成后关闭。')
            return
        self.destroy()

    def destroy(self):
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        super().destroy()


def main(argv=None):
    argv = list(argv or [])
    unknown = [argument for argument in argv if argument != '--smoke-test']
    if unknown:
        raise SystemExit(f'未知参数：{unknown[0]}')
    app = App()
    if '--smoke-test' in argv:
        app.after_idle(app.destroy)
    app.mainloop()
    return 0


if __name__ == '__main__':
    import sys
    raise SystemExit(main(sys.argv[1:]))
