import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.photo_storage import NetworkPhotoStore, StorageUnavailable, StorageConflict, sanitize, folder_key, rename_exclusive


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
        with self.assertRaises(StorageUnavailable):store.prepare(900, 'Server', 1,'channel',2,'x.jpg')
        self.assertFalse(missing.exists());self.assertFalse(store.state_file.exists())

    def test_unicode_channel_identity_rename_and_case_collision(self):
        self.assertEqual(sanitize('🐶-pets'),'🐶-pets')
        self.assertEqual(sanitize('𝒟𝒩𝒟-𝒜ℛ𝒯'),'𝒟𝒩𝒟-𝒜ℛ𝒯')
        self.assertEqual(sanitize('..'),'unknown')
        with self.guard:
            p=self.store.prepare(900, 'Server', 10,'𝒟𝒩𝒟-𝒜ℛ𝒯',11,'照片.jpg')
            p.file.write(b'photo');p.finish(5);p.close()
            self.assertTrue((self.base/'Server'/'𝒟𝒩𝒟-𝒜ℛ𝒯'/'11_照片.jpg').exists())
            p=self.store.prepare(900, 'Server', 10,'Renamed',12,'photo.jpg');p.file.write(b'next');p.finish(4);p.close()
            self.assertFalse((self.base/'Server'/'Renamed').exists())
            p=self.store.prepare(900, 'Server', 40,'Alpha',41,'x.jpg');p.close()
            p=self.store.prepare(900, 'Server', 50,'alpha',51,'x.jpg');p.close()
            self.assertTrue((self.base/'Server'/'alpha (2)').exists())
            p=self.store.prepare(900, 'Server', 20,'𝒟𝒩𝒟-𝒜ℛ𝒯',21,'new.jpg');p.close()
            self.assertTrue((self.base/'Server'/'𝒟𝒩𝒟-𝒜ℛ𝒯 (2)').exists())
            (self.base/'Server'/'old-folder').mkdir()
            p=self.store.prepare(900, 'Server', 30,'old-folder',31,'new.jpg');p.close()
            self.assertTrue((self.base/'Server'/'old-folder (2)').exists())

    def test_global_attachment_duplicate_is_not_downloaded_or_renamed(self):
        (self.base/'legacy').mkdir();(self.base/'legacy'/'100_old.jpg').write_bytes(b'existing')
        with self.guard:self.assertIsNone(self.store.prepare(900, 'Server', 10,'new-channel',100,'renamed.jpg'))
        self.assertFalse((self.base/'new-channel').exists())
        with self.guard:
            with self.assertRaises(StorageConflict):self.store.prepare(900, 'Server', 10,'new-channel',100,'renamed.jpg',99)

    def test_atomic_no_overwrite_and_partial_cleanup(self):
        with self.guard:
            p=self.store.prepare(900, 'Server', 1,'channel',2,'photo.jpg');p.file.write(b'new')
            target=self.base/'Server'/'channel'/'2_photo.jpg';target.write_bytes(b'original')
            try:
                with self.assertRaises(FileExistsError):p.finish(3)
            finally:p.close()
            self.assertEqual(target.read_bytes(),b'original')
            self.assertFalse(list(self.base.rglob('*.partial')))

    def test_incomplete_and_checksum_mismatch_not_published(self):
        with self.guard:
            for size,digest in [(100,None),(3,'bad-hash')]:
                p=self.store.prepare(900, 'Server', 1,'channel',2,'photo.jpg');p.file.write(b'new')
                try:
                    with self.assertRaises(StorageConflict):p.finish(size,digest)
                finally:p.close()
                self.assertFalse((self.base/'Server'/'channel'/'2_photo.jpg').exists())

    def test_mount_loss_and_replaced_underlying_directory_fail_closed(self):
        with self.guard:p=self.store.prepare(900, 'Server', 1,'channel',2,'photo.jpg')
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
        elsewhere=self.mount/'elsewhere';elsewhere.mkdir();(self.base/'Server').mkdir();(self.base/'Server'/'channel').symlink_to(elsewhere,target_is_directory=True)
        self.store.mapping={'schema_version':2,'servers':{'900':{'folder':'Server','channels':{'1':{'folder':'channel'}}}}}
        with self.guard:
            with self.assertRaises(OSError):self.store.prepare(900, 'Server', 1,'channel',2,'x.jpg')
        self.assertEqual(list(elsewhere.iterdir()),[])

    def test_windows_names(self):
        for name in ['CON', 'con.txt', 'NUL', 'COM1', 'Lpt9.jpg', 'COM¹']:
            self.assertTrue(sanitize(name).startswith('_'))
        self.assertEqual(sanitize(' A<>:"/\\|?*\x00\n. '), ' A___________')
        for name in ['', '.', '..', '   ']:self.assertEqual(sanitize(name),'unknown')
        self.assertEqual(sanitize('D&D 照片 🐶'), 'D&D 照片 🐶')
        self.assertEqual(sanitize('a\x7f\x85b'), 'a__b')
        self.assertEqual(folder_key('Café. '),folder_key('CAFE\u0301'))

    def test_server_identity_rename_collision_and_cross_server_dedup(self):
        with self.guard:
            p=self.store.prepare(1,'First',10,'session-notes',100,'photo.jpg');p.file.write(b'a');p.finish(1);p.close()
            p=self.store.prepare(1,'Renamed',10,'renamed',101,'photo.jpg');p.close()
            p=self.store.prepare(2,'first',20,'session-notes',102,'photo.jpg');p.close()
            self.assertTrue((self.base/'First'/'session-notes'/'100_photo.jpg').exists())
            self.assertTrue((self.base/'first (2)'/'session-notes').exists())
            reloaded=NetworkPhotoStore(self.base,self.mount,self.store.state_file)
            self.assertEqual(reloaded.mapping,self.store.mapping)
            self.assertIsNone(reloaded.prepare(2,'first',20,'session-notes',100,'renamed.jpg',1))
            with self.assertRaises(StorageConflict):reloaded.prepare(2,'first',20,'session-notes',100,'renamed.jpg',2)

    def test_directory_migration_no_replace_and_global_dedup(self):
        source=self.base/'legacy';source.mkdir();(source/'100_old.jpg').write_bytes(b'media')
        target=self.base/'Server';target.mkdir();(target/'occupied').mkdir()
        fd=os.open(self.base,os.O_RDONLY|os.O_DIRECTORY)
        try:
            with self.assertRaises(FileExistsError):rename_exclusive(fd,'legacy','Server/occupied')
            self.assertEqual((source/'100_old.jpg').read_bytes(),b'media')
            rename_exclusive(fd,'legacy','Server/migrated')
        finally:os.close(fd)
        self.assertEqual((target/'migrated'/'100_old.jpg').read_bytes(),b'media')
        with self.guard:self.assertIsNone(self.store.prepare(1,'Other',10,'new',100,'other.jpg',5))

    def test_dedup_in_dot_prefixed_server_folder(self):
        folder=self.base/'.Server'/'channel';folder.mkdir(parents=True)
        (folder/'100_photo.jpg').write_bytes(b'old')
        with self.guard:self.assertIsNone(self.store.prepare(1,'Other',1,'new',100,'x.jpg',3))

    def test_duplicate_private_assignments_fail_closed(self):
        self.store.mapping={'schema_version':2,'servers':{
            '1':{'folder':'First','channels':{}},'2':{'folder':'FIRST','channels':{}}}}
        with self.assertRaises(StorageConflict):self.store.validate_mapping()
        self.store.mapping['servers']['2']['folder']='Second'
        for server in self.store.mapping['servers'].values():server['channels']['10']={'folder':'notes'}
        with self.assertRaises(StorageConflict):self.store.validate_mapping()

    def test_existing_server_is_not_adopted_and_mapping_write_failure_is_atomic(self):
        (self.base/'SERVER.').mkdir()
        with self.guard:
            p=self.store.prepare(1,'server',1,'notes',2,'x.jpg');p.close()
        self.assertEqual(self.store.mapping['servers']['1']['folder'],'server (2)')
        self.assertFalse(list((self.base/'SERVER.').iterdir()))
        before=self.store.state_file.read_bytes()
        with self.guard, patch('src.photo_storage.os.replace',side_effect=OSError):
            with self.assertRaises(OSError):self.store.prepare(2,'new',3,'notes',4,'x.jpg')
        self.assertEqual(self.store.state_file.read_bytes(),before)
        self.assertNotIn('2',self.store.mapping['servers'])

    def test_unresolved_legacy_channel_fails_closed_without_new_assignment(self):
        self.store.mapping['unresolved_legacy_channels']={'10':{'folder':'legacy'}}
        with self.guard:
            with self.assertRaises(StorageConflict):self.store.prepare(1,'Server',10,'new',11,'x.jpg')
        self.assertFalse(list(self.base.iterdir()))
        self.assertFalse(self.store.state_file.exists())

    def test_legacy_mapping_requires_offline_migration(self):
        self.store.state_file.parent.mkdir();self.store.state_file.write_text('{"10":{"folder":"legacy"}}')
        with self.assertRaises(StorageConflict):NetworkPhotoStore(self.base,self.mount,self.store.state_file)

    def test_unsafe_mapping_and_server_symlink_rejected(self):
        self.store.mapping={'schema_version':2,'servers':{'1':{'folder':'../escape','channels':{}}}}
        with self.guard:
            with self.assertRaises(StorageConflict):self.store.prepare(1,'Server',1,'x',1,'x.jpg')
        self.store.mapping={'schema_version':2,'servers':{}}
        elsewhere=self.mount/'other';elsewhere.mkdir();(self.base/'Linked').symlink_to(elsewhere,target_is_directory=True)
        self.store.mapping['servers']['1']={'folder':'Linked','channels':{}}
        with self.guard:
            with self.assertRaises(OSError):self.store.prepare(1,'Linked',1,'x',1,'x.jpg')
        self.assertFalse(list(elsewhere.iterdir()))

if __name__=='__main__':unittest.main()
