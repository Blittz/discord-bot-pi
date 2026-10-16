import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.attachment_policy import attachment_skip_reason
from src.cogs.photosaver import PhotoSaver


class AttachmentPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_channel_flags(self):
        for kind in (0, 2, 5, 13, 15, 16):
            for flag, expected in [(False, None), (True, 'age-restricted'),
                                   (None, 'restriction-unknown'), (0, 'restriction-unknown')]:
                http = SimpleNamespace(get_channel=AsyncMock(return_value={'id': '1', 'type': kind, 'nsfw': flag}))
                self.assertEqual(await attachment_skip_reason(http, 1), expected)

    async def test_threads_and_forum_posts_check_fresh_parent(self):
        for kind in (10, 11, 12):
            for parent_kind in (0, 5, 15, 16):
                for flag, expected in [(False, None), (True, 'parent-age-restricted'),
                                       (None, 'parent-restriction-unknown')]:
                    http = SimpleNamespace(get_channel=AsyncMock(side_effect=[
                        {'id': '1', 'type': kind, 'parent_id': '2'},
                        {'id': '2', 'type': parent_kind, 'nsfw': flag}]))
                    self.assertEqual(await attachment_skip_reason(http, 1), expected)
                    self.assertEqual(http.get_channel.await_count, 2)

    async def test_missing_malformed_or_unavailable_metadata_blocks(self):
        for data in ({}, None, {'id': '9', 'type': 0, 'nsfw': False},
                     {'id': '1', 'type': 0}, {'id': '1', 'type': 1},
                     {'id': '1', 'type': 11}, {'id': '1', 'type': 11, 'parent_id': None}):
            http = SimpleNamespace(get_channel=AsyncMock(return_value=data))
            self.assertIsNotNone(await attachment_skip_reason(http, 1))
        for failure in (PermissionError('private error'), TimeoutError('private error')):
            http = SimpleNamespace(get_channel=AsyncMock(side_effect=failure))
            self.assertEqual(await attachment_skip_reason(http, 1), 'restriction-metadata-unavailable')
        http = SimpleNamespace(get_channel=AsyncMock(side_effect=[
            {'id': '1', 'type': 11, 'parent_id': '2'}, PermissionError('private')]))
        self.assertIsNotNone(await attachment_skip_reason(http, 1))

    async def test_thread_own_restriction_and_malformed_parent_block(self):
        for thread, parent in [
            ({'id': '1', 'type': 11, 'nsfw': True, 'parent_id': '2'}, None),
            ({'id': '1', 'type': 11, 'parent_id': '2'}, {'id': '3', 'type': 0, 'nsfw': False}),
            ({'id': '1', 'type': 11, 'parent_id': '2'}, {'id': '2', 'type': 4, 'nsfw': False}),
        ]:
            http = SimpleNamespace(get_channel=AsyncMock(side_effect=[thread, parent]))
            self.assertIsNotNone(await attachment_skip_reason(http, 1))

    def cog(self, http):
        cog = object.__new__(PhotoSaver)
        cog.bot = SimpleNamespace(http=http)
        cog.store = Mock()
        cog._storage_lock = asyncio.Lock()
        return cog

    async def test_image_and_video_skipped_before_storage_or_download(self):
        for mime, filename in [('image/jpeg', 'test.jpg'), ('video/mp4', 'test.mp4')]:
            for reason in ('age-restricted', 'parent-age-restricted', 'restriction-metadata-unavailable'):
                cog = self.cog(Mock())
                attachment = SimpleNamespace(content_type=mime, filename=filename, save=AsyncMock())
                with patch('src.cogs.photosaver.attachment_skip_reason', AsyncMock(return_value=reason)):
                    with self.assertLogs('src.cogs.photosaver', level='INFO') as logs:
                        await cog.save_attachments(SimpleNamespace(id=1, name='private-name'), [attachment])
                cog.store.prepare.assert_not_called()
                attachment.save.assert_not_awaited()
                self.assertNotIn('private-name', ' '.join(logs.output))

    async def test_each_attachment_rechecks_and_preserves_duplicate_handling(self):
        http = SimpleNamespace(get_channel=AsyncMock(side_effect=[
            {'id': '1', 'type': 0, 'nsfw': False}, {'id': '1', 'type': 0, 'nsfw': True}]))
        cog = self.cog(http)
        cog.store.prepare.return_value = None
        attachments = [SimpleNamespace(id=i, filename='test.jpg', content_type='image/jpeg',
                                       size=3, save=AsyncMock()) for i in (2, 3)]
        await cog.save_attachments(SimpleNamespace(id=1, name='example'), attachments)
        self.assertEqual(cog.store.prepare.call_count, 1)
        self.assertEqual(http.get_channel.await_count, 2)
        for attachment in attachments:
            attachment.save.assert_not_awaited()

    async def test_allowed_download_finishes_and_closes(self):
        http = SimpleNamespace(get_channel=AsyncMock(return_value={'id': '1', 'type': 0, 'nsfw': False}))
        cog = self.cog(http)
        pending = cog.store.prepare.return_value
        attachment = SimpleNamespace(id=2, filename='test.mp4', content_type='video/mp4', size=3, save=AsyncMock())
        await cog.save_attachments(SimpleNamespace(id=1, name='example'), [attachment])
        attachment.save.assert_awaited_once_with(pending.file)
        pending.finish.assert_called_once_with(3)
        pending.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
