"""Fail-closed, mount-anchored photo storage with immutable attachment IDs."""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unicodedata
import uuid


class StorageUnavailable(OSError):
    pass


class StorageConflict(OSError):
    pass


def sanitize(value, fallback='unknown'):
    # Preserve the established mapping, including decorative Unicode letters.
    safe = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in value.strip()).strip('_')
    return safe if safe and safe not in ('.', '..') else fallback


def folder_key(value):
    return unicodedata.normalize('NFC', value).casefold()


def digest_file(file):
    file.seek(0)
    digest = hashlib.sha256()
    for block in iter(lambda: file.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def mounted_share(path, required_mount, required_fs='cifs'):
    path, required_mount = Path(path).absolute(), Path(required_mount).absolute()
    try:
        path.relative_to(required_mount)
    except ValueError:
        raise StorageUnavailable('Destination is outside required mount')
    # Trigger autofs if available; never create a directory before validation.
    os.stat(required_mount)
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split(); separator = fields.index('-')
        mountpoint = fields[4]
        for escaped, char in [('\\040',' '),('\\011','\t'),('\\134','\\')]:
            mountpoint = mountpoint.replace(escaped, char)
        if mountpoint == str(required_mount) and fields[separator + 1] == required_fs:
            major, minor = map(int, fields[2].split(':'))
            return fields[0], os.makedev(major, minor)
    raise StorageUnavailable('Required network filesystem is not mounted')


def open_base(path, required_mount, required_fs='cifs'):
    identity = mounted_share(path, required_mount, required_fs)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(required_mount, flags)
    try:
        if os.fstat(fd).st_dev != identity[1]:
            raise StorageUnavailable('Mount changed during directory open')
        for part in Path(path).absolute().relative_to(Path(required_mount).absolute()).parts:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd); fd = child
        if os.fstat(fd).st_dev != identity[1] or mounted_share(path, required_mount, required_fs) != identity:
            raise StorageUnavailable('Mount changed during destination open')
        if os.fstatvfs(fd).f_flag & os.ST_RDONLY:
            raise StorageUnavailable('Network destination is read-only')
        return fd, identity
    except BaseException:
        os.close(fd)
        raise


def attachment_index(fd):
    result = {}
    # This path remains anchored to the open network fd across a lazy unmount.
    for root, dirs, files in os.walk('/proc/self/fd/' + str(fd), followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and not Path(root, d).is_symlink()]
        for filename in files:
            aid = filename.split('_', 1)[0]
            if aid.isdigit() and not Path(root, filename).is_symlink():
                relative = str(Path(root, filename).relative_to('/proc/self/fd/' + str(fd)))
                result.setdefault(aid, []).append(relative)
    return result


def rename_exclusive(directory_fd, source, target):
    libc = ctypes.CDLL(None, use_errno=True)
    fn = libc.renameat2
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(directory_fd, os.fsencode(source), directory_fd, os.fsencode(target), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


class PendingFile:
    def __init__(self, store, base_fd, identity, folder, filename):
        self.store, self.base_fd, self.identity = store, base_fd, identity
        self.directory_fd = None
        self.file = None
        self.temporary = None
        self.filename = filename
        try:
            if folder_key(folder) in ('.', '..') or '/' in folder or not folder:
                raise StorageConflict('Unsafe folder')
            # Anchored mkdir/open can never fall through to an underlying local mountpoint.
            try: os.mkdir(folder, dir_fd=base_fd)
            except FileExistsError: pass
            self.directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd)
            try:
                os.stat(filename, dir_fd=self.directory_fd, follow_symlinks=False)
                raise StorageConflict('Target already exists')
            except FileNotFoundError: pass
            self.temporary = '.photo-' + uuid.uuid4().hex + '.partial'
            raw = os.open(self.temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=self.directory_fd)
            self.file = os.fdopen(raw, 'w+b')
        except BaseException:
            self.close()
            raise

    def finish(self, expected_size, expected_hash=None):
        self.file.flush(); os.fsync(self.file.fileno())
        if os.fstat(self.file.fileno()).st_size != expected_size:
            raise StorageConflict('Incomplete attachment')
        digest = digest_file(self.file)
        if expected_hash is not None and digest != expected_hash:
            raise StorageConflict('Content checksum mismatch')
        if mounted_share(self.store.base, self.store.mount, self.store.fs) != self.identity:
            raise StorageUnavailable('Network mount changed before publish')
        rename_exclusive(self.directory_fd, self.temporary, self.filename)
        self.temporary = None
        # Verify the actual published file too, rather than trusting the write.
        fd = os.open(self.filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.directory_fd)
        with os.fdopen(fd, 'rb') as published:
            if digest_file(published) != digest:
                raise StorageConflict('Published content checksum mismatch')
        return digest

    def close(self):
        if self.file is not None:
            self.file.close(); self.file = None
        if self.directory_fd is not None:
            if self.temporary is not None:
                try: os.unlink(self.temporary, dir_fd=self.directory_fd)
                except OSError: pass
            os.close(self.directory_fd); self.directory_fd = None
        if self.base_fd is not None:
            os.close(self.base_fd); self.base_fd = None


class NetworkPhotoStore:
    def __init__(self, base, mount, state_file, fs='cifs'):
        self.base, self.mount, self.fs = Path(base).absolute(), Path(mount).absolute(), fs
        self.state_file = Path(state_file)
        self.mapping = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def verify(self):
        fd, identity = open_base(self.base, self.mount, self.fs)
        os.close(fd)
        return identity

    def folder_for(self, channel_id, channel_name, base_fd):
        key = str(channel_id)
        if key in self.mapping:
            return self.mapping[key]['folder']
        folder = sanitize(channel_name, 'unknown')
        if any(folder_key(v['folder']) == folder_key(folder) for v in self.mapping.values()):
            raise StorageConflict('Channel folder collision; needs explicit mapping')
        if any(folder_key(name) == folder_key(folder) for name in os.listdir(base_fd)):
            raise StorageConflict('Existing unassigned folder; needs explicit mapping')
        self.mapping[key] = {'folder': folder}
        self.state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw, temp = tempfile.mkstemp(prefix='.channels-', dir=self.state_file.parent)
        try:
            with os.fdopen(raw, 'w') as file:
                json.dump(self.mapping, file, ensure_ascii=False, indent=2)
                file.flush(); os.fsync(file.fileno())
            os.replace(temp, self.state_file)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return folder

    def prepare(self, channel_id, channel_name, attachment_id, filename, expected_size=None):
        base_fd, identity = open_base(self.base, self.mount, self.fs)
        try:
            duplicates = attachment_index(base_fd).get(str(attachment_id), [])
            if duplicates:
                if expected_size is not None and not any(os.stat(name, dir_fd=base_fd, follow_symlinks=False).st_size == expected_size for name in duplicates):
                    raise StorageConflict('Existing attachment ID has a different size')
                os.close(base_fd)
                return None
            folder = self.folder_for(channel_id, channel_name, base_fd)
        except BaseException:
            os.close(base_fd)
            raise
        return PendingFile(self, base_fd, identity, folder,
                           str(attachment_id) + '_' + sanitize(filename, str(attachment_id)))
