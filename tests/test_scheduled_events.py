import asyncio
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
from src.scheduled_events import EventExporter,atomic_snapshot,normalize_event

NOW=datetime(2026,10,16,12,tzinfo=timezone.utc)
GUILD=SimpleNamespace(id=1,name='Example server')


def raw(eid='10',kind=3,channel=None,status=1):
    return {'id':eid,'guild_id':'1','name':'Example session','entity_type':kind,'channel_id':channel,
            'status':status,'scheduled_start_time':(NOW+timedelta(hours=2)).isoformat(),
            'scheduled_end_time':None,'description':'private description','user_count':99,
            'creator':{'id':'private'},'entity_metadata':{'location':'private invite'},'image':'private'}


class ScheduledEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'state/events.json'
        self.http=SimpleNamespace(get_scheduled_events=AsyncMock(return_value=[]),get_channel=AsyncMock())
        self.exporter=EventExporter(self.http,self.path)

    async def test_external_missing_end_and_whitelisted_export(self):
        self.http.get_scheduled_events.return_value=[raw()]
        counts=await self.exporter.refresh([GUILD],NOW)
        self.assertTrue(counts['complete']);self.assertEqual(counts['events'],1)
        self.http.get_channel.assert_not_awaited()
        self.http.get_scheduled_events.assert_awaited_once_with(1,with_user_count=False)
        data=json.loads(self.path.read_text());event=data['events'][0]
        self.assertEqual(event['kind'],'external');self.assertIsNone(event['channel_id'])
        self.assertIsNone(event['end_at']);self.assertNotIn('nsfw',event)
        self.assertNotIn('private',self.path.read_text());self.assertNotIn('user_count',self.path.read_text())
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)

    async def test_restricted_unknown_and_parent_age_gate(self):
        self.http.get_scheduled_events.return_value=[raw('10',2,'2'),raw('11',2,'3'),raw('12',2,'4'),raw('13',2,'5')]
        async def channel(cid):
            return {2:{'id':'2','type':2,'nsfw':False},3:{'id':'3','type':2,'nsfw':True},
                    4:{'id':'4','type':2},5:{'id':'5','type':11,'parent_id':'6'},
                    6:{'id':'6','type':15,'nsfw':True}}[cid]
        self.http.get_channel.side_effect=channel
        counts=await self.exporter.refresh([GUILD],NOW)
        self.assertEqual([e['id'] for e in self.exporter.snapshot['events']],['10'])
        self.assertEqual(counts['excluded_restricted'],2);self.assertEqual(counts['excluded_unverified'],1)
        self.assertFalse(counts['complete'])

    async def test_channel_lookup_once_per_refresh_not_cached_between_refreshes(self):
        self.http.get_scheduled_events.return_value=[raw('10',2,'2'),raw('11',2,'2')]
        self.http.get_channel.return_value={'id':'2','type':2,'nsfw':False}
        await self.exporter.refresh([GUILD],NOW)
        self.assertEqual(self.http.get_channel.await_count,1)
        self.http.get_channel.return_value={'id':'2','type':2,'nsfw':True}
        await self.exporter.refresh([GUILD],NOW+timedelta(minutes=5))
        self.assertEqual(self.exporter.snapshot['events'],[])
        self.assertEqual(self.http.get_channel.await_count,2)

    async def test_failure_preserves_external_but_never_unverifiable_channel(self):
        self.http.get_scheduled_events.return_value=[raw(),raw('11',2,'2')]
        self.http.get_channel.return_value={'id':'2','type':2,'nsfw':False}
        await self.exporter.refresh([GUILD],NOW)
        self.http.get_scheduled_events.side_effect=PermissionError('private signed URL')
        self.http.get_channel.side_effect=PermissionError('private signed URL')
        await self.exporter.refresh([GUILD],NOW+timedelta(minutes=5))
        self.assertFalse(self.exporter.snapshot['refresh_ok'])
        self.assertEqual(self.exporter.snapshot['last_successful_refresh'],NOW.isoformat())
        self.assertEqual([e['id'] for e in self.exporter.snapshot['events']],['10'])
        self.assertNotIn('private',self.path.read_text())

    async def test_cancellation_completion_reschedule_and_server_removal(self):
        self.http.get_scheduled_events.return_value=[raw('10'),raw('11',status=2),raw('12',status=3),raw('13',status=4)]
        await self.exporter.refresh([GUILD],NOW)
        self.assertEqual([e['status'] for e in self.exporter.snapshot['events']],['scheduled','active'])
        changed=raw('10');changed['scheduled_start_time']=(NOW+timedelta(days=3)).isoformat()
        self.http.get_scheduled_events.return_value=[changed]
        await self.exporter.refresh([GUILD],NOW)
        self.assertEqual(len(self.exporter.snapshot['events']),1)
        self.assertIn('2026-10-19',self.exporter.snapshot['events'][0]['start_at'])
        await self.exporter.refresh([],NOW)
        self.assertEqual(self.exporter.snapshot['events'],[])

    async def test_restart_retains_last_valid_external_data_on_fetch_failure(self):
        self.http.get_scheduled_events.return_value=[raw()]
        await self.exporter.refresh([GUILD],NOW)
        restored=EventExporter(self.http,self.path)
        self.http.get_scheduled_events.side_effect=TimeoutError()
        await restored.refresh([GUILD],NOW+timedelta(minutes=5))
        self.assertEqual(len(restored.snapshot['events']),1)
        self.assertFalse(restored.snapshot['refresh_ok'])

    async def test_multi_server_partial_failure_does_not_advance_global_success(self):
        other=SimpleNamespace(id=2,name='Second server')
        self.http.get_scheduled_events.return_value=[]
        await self.exporter.refresh([GUILD,other],NOW)
        self.http.get_scheduled_events.side_effect=[[],PermissionError()]
        await self.exporter.refresh([GUILD,other],NOW+timedelta(minutes=5))
        self.assertFalse(self.exporter.snapshot['refresh_ok'])
        self.assertEqual(self.exporter.snapshot['last_successful_refresh'],NOW.isoformat())
        self.assertEqual([s['refresh_ok'] for s in self.exporter.snapshot['servers']],[True,False])

    async def test_atomic_write_failure_preserves_previous_snapshot(self):
        await self.exporter.refresh([GUILD],NOW)
        before=self.path.read_bytes()
        with patch('src.scheduled_events.os.replace',side_effect=OSError):
            with self.assertRaises(OSError):atomic_snapshot(self.path,{'new':'snapshot'})
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.glob('.events-*.tmp')),[])

    async def test_invite_links_in_titles_are_redacted(self):
        entry=raw();entry['name']='Adventure https://discord.gg/example-secret'
        result=normalize_event(entry,1)
        self.assertIn('[invite omitted]',result['title'])
        self.assertNotIn('example-secret',result['title'])
        self.assertNotIn('discord.gg',result['title'])

    async def test_invalid_or_naive_event_not_exported_as_fresh(self):
        for key,value in [('scheduled_start_time','2026-10-17T10:00:00'),('entity_type',99),('guild_id','9')]:
            event=raw();event[key]=value
            with self.assertRaises(ValueError):normalize_event(event,1)

    async def test_gateway_updates_wake_refresh_without_discord_mutations(self):
        from src.cogs.events import ScheduledEvents
        cog=object.__new__(ScheduledEvents);cog.wakeup=asyncio.Event()
        for method,args in [('on_scheduled_event_create',(None,)),('on_scheduled_event_update',(None,None)),
                            ('on_scheduled_event_delete',(None,)),('on_guild_channel_update',(None,None))]:
            cog.wakeup.clear();await getattr(cog,method)(*args);self.assertTrue(cog.wakeup.is_set())


if __name__=='__main__':unittest.main()
