import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.photo_storage import NetworkPhotoStore, StorageUnavailable, StorageConflict, sanitize, folder_key


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.mount=Path(self.tmp.name);self.base=self.mount/'photos';self.base.mkdir()
        self.store=NetworkPhotoStore(self.base,self.mount,self.mount/'state'/'channels.json')
        self.identity=('test',self.mount.stat().st_dev)
        self.guard=patch('src.photo_storage.mounted_share',return_value=self.identity)

    def test_missing_mount_never_creates_local_destination(self):
        missing=self.mount/'missing'
        store=NetworkPhotoStore(missing,self.mount,self.mount/'state.json')
        with self.assertRaises(StorageUnavailable):store.prepare(1,'channel',2,'x.jpg')
        self.assertFalse(missing.exists());self.assertFalse(store.state_file.exists())

    def test_unicode_channel_identity_rename_and_case_collision(self):
        self.assertEqual(sanitize('🐶-pets'),'-pets')
        self.assertEqual(sanitize('𝒟𝒩𝒟-𝒜ℛ𝒯'),'𝒟𝒩𝒟-𝒜ℛ𝒯')
        self.assertEqual(sanitize('..'),'unknown')
        with self.guard:
            p=self.store.prepare(10,'𝒟𝒩𝒟-𝒜ℛ𝒯',11,'照片.jpg')
            p.file.write(b'photo');p.finish(5);p.close()
            self.assertTrue((self.base/'𝒟𝒩𝒟-𝒜ℛ𝒯'/'11_照片.jpg').exists())
            p=self.store.prepare(10,'Renamed',12,'photo.jpg');p.file.write(b'next');p.finish(4);p.close()
            self.assertFalse((self.base/'Renamed').exists())
            p=self.store.prepare(40,'Alpha',41,'x.jpg');p.close()
            with self.assertRaises(StorageConflict):self.store.prepare(50,'alpha',51,'x.jpg')
            with self.assertRaises(StorageConflict):self.store.prepare(20,'𝒟𝒩𝒟-𝒜ℛ𝒯',21,'new.jpg')
            with self.assertRaises(StorageConflict):self._existing_unassigned()

    def _existing_unassigned(self):
        (self.base/'old-folder').mkdir()
        return self.store.prepare(30,'old-folder',31,'new.jpg')

    def test_global_attachment_duplicate_is_not_downloaded_or_renamed(self):
        (self.base/'legacy').mkdir();(self.base/'legacy'/'100_old.jpg').write_bytes(b'existing')
        with self.guard:self.assertIsNone(self.store.prepare(10,'new-channel',100,'renamed.jpg'))
        self.assertFalse((self.base/'new-channel').exists())
        with self.guard:
            with self.assertRaises(StorageConflict):self.store.prepare(10,'new-channel',100,'renamed.jpg',99)

    def test_atomic_no_overwrite_and_partial_cleanup(self):
        with self.guard:
            p=self.store.prepare(1,'channel',2,'photo.jpg');p.file.write(b'new')
            target=self.base/'channel'/'2_photo.jpg';target.write_bytes(b'original')
            try:
                with self.assertRaises(FileExistsError):p.finish(3)
            finally:p.close()
            self.assertEqual(target.read_bytes(),b'original')
            self.assertFalse(list(self.base.rglob('*.partial')))

    def test_incomplete_and_checksum_mismatch_not_published(self):
        with self.guard:
            for size,digest in [(100,None),(3,'bad-hash')]:
                p=self.store.prepare(1,'channel',2,'photo.jpg');p.file.write(b'new')
                try:
                    with self.assertRaises(StorageConflict):p.finish(size,digest)
                finally:p.close()
                self.assertFalse((self.base/'channel'/'2_photo.jpg').exists())

    def test_mount_loss_and_replaced_underlying_directory_fail_closed(self):
        with self.guard:p=self.store.prepare(1,'channel',2,'photo.jpg')
        p.file.write(b'new')
        moved=self.mount/'detached';self.base.rename(moved);self.base.mkdir()
        try:
            with patch('src.photo_storage.mounted_share',side_effect=StorageUnavailable('unmounted')):
                with self.assertRaises(StorageUnavailable):p.finish(3)
        finally:p.close()
        self.assertEqual(list(self.base.iterdir()),[])
        self.assertFalse(list(moved.rglob('*.partial')))
        self.assertFalse(list(moved.rglob('*.jpg')))

    def test_channel_symlink_rejected(self):
        elsewhere=self.mount/'elsewhere';elsewhere.mkdir();(self.base/'channel').symlink_to(elsewhere,target_is_directory=True)
        self.store.mapping={'1':{'folder':'channel'}}
        with self.guard:
            with self.assertRaises(OSError):self.store.prepare(1,'channel',2,'x.jpg')
        self.assertEqual(list(elsewhere.iterdir()),[])

if __name__=='__main__':unittest.main()
