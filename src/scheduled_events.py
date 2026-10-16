"""Minimal private scheduled-event snapshots; Discord access is GET-only."""
import asyncio
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import tempfile

from src.attachment_policy import attachment_skip_reason

DEFAULT_EVENTS_FILE = Path.home()/'.local/state/discord-photo-viewer/events.json'
MAX_BYTES = 256 * 1024
STATUS = {1:'scheduled', 2:'active', 3:'completed', 4:'canceled'}
EVENT_KEYS = ('id','server_id','title','start_at','end_at','status','kind','channel_id')
SERVER_KEYS = ('id','name','last_successful_refresh','refresh_ok')


def timestamp(value):
    if not isinstance(value,str):
        raise ValueError('Invalid timestamp')
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('Timezone missing')
    return dt.astimezone(timezone.utc).isoformat()


def normalize_event(raw, server_id):
    if str(raw.get('guild_id')) != str(server_id):
        raise ValueError('Server mismatch')
    kind = raw.get('entity_type')
    channel = raw.get('channel_id')
    if kind == 3 and channel is None:
        kind = 'external'
    elif kind in (1,2) and isinstance(channel,(str,int)) and str(channel).isdigit():
        kind,channel = 'channel',str(channel)
    else:
        raise ValueError('Unknown event association')
    title = raw.get('name')
    if not isinstance(title,str) or not title.strip() or len(title)>100:
        raise ValueError('Invalid title')
    if not str(raw.get('id','')).isdigit() or raw.get('status') not in STATUS:
        raise ValueError('Invalid event')
    start = timestamp(raw.get('scheduled_start_time'))
    end = timestamp(raw['scheduled_end_time']) if raw.get('scheduled_end_time') else None
    if end and datetime.fromisoformat(end) <= datetime.fromisoformat(start):
        raise ValueError('End before start')
    title=re.sub(r'(?i)(?:https?://)?(?:www\.)?(?:discord\.gg/|discord(?:app)?\.com/invite/)\S+',
                 '[invite omitted]', ' '.join(title.split()))[:100]
    return {'id':str(raw['id']), 'server_id':str(server_id), 'title':title,
            'start_at':start,'end_at':end,'status':STATUS[raw['status']],
            'kind':kind,'channel_id':channel}


def atomic_snapshot(path, payload):
    path=Path(path)
    data=(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    if len(data)>MAX_BYTES:
        raise ValueError('Snapshot too large')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.events-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as file:
            file.write(data);file.flush();os.fsync(file.fileno())
        os.replace(temp,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temp):os.unlink(temp)


class EventExporter:
    def __init__(self,http,path=DEFAULT_EVENTS_FILE):
        self.http,self.path=http,Path(path)
        self.snapshot={}
        self.last_counts=None
        try:
            with self.path.open('rb') as file:data=json.loads(file.read(MAX_BYTES+1))
            if data.get('schema_version')==1:
                # Whitelist even private on-disk data; never re-export extra fields.
                self.snapshot={k:data.get(k) for k in ('last_successful_refresh',)}
                self.snapshot['servers']=[{k:s.get(k) for k in SERVER_KEYS} for s in data['servers']]
                self.snapshot['events']=[{k:e.get(k) for k in EVENT_KEYS} for e in data['events']]
        except (OSError,ValueError,TypeError,KeyError):
            pass

    async def refresh(self,guilds,now=None):
        now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        servers,events=[],[]
        previous={s['id']:s for s in self.snapshot.get('servers',[])}
        excluded=unverified=0
        # One fresh age check per channel per refresh, shared across its events.
        restrictions={}
        async def allowed(event):
            nonlocal excluded,unverified
            if event['kind']=='external' and event['channel_id'] is None:
                return True
            cid=event.get('channel_id')
            if event.get('kind')!='channel' or not isinstance(cid,str) or not cid.isdigit():
                unverified+=1;return False
            if cid not in restrictions:
                try:restrictions[cid]=await asyncio.wait_for(attachment_skip_reason(self.http,int(cid)),20)
                except (asyncio.TimeoutError,OSError):restrictions[cid]='restriction-metadata-unavailable'
            reason=restrictions[cid]
            if reason in ('age-restricted','parent-age-restricted'):
                excluded+=1;return False
            if reason:
                unverified+=1;return False
            return True
        for guild in guilds:
            sid=str(guild.id)
            complete=True
            count_before=unverified
            try:
                raw=await asyncio.wait_for(self.http.get_scheduled_events(guild.id,with_user_count=False),20)
                if not isinstance(raw,list):raise ValueError('Invalid events')
                current=[]
                for item in raw:
                    event=normalize_event(item,sid)
                    if event['status'] in ('scheduled','active') and await allowed(event):current.append(event)
            except Exception:
                complete=False
                current=[]
                for event in self.snapshot.get('events',[]):
                    if event.get('server_id')==sid and event.get('status') in ('scheduled','active'):
                        # Privacy wins over retaining an unverifiable channel event.
                        if await allowed(event):current.append(event)
            complete=complete and unverified==count_before
            events.extend(current)
            servers.append({'id':sid,'name':str(guild.name)[:100], 'refresh_ok':complete,
                            'last_successful_refresh':now if complete else previous.get(sid,{}).get('last_successful_refresh')})
        complete=bool(servers) and all(s['refresh_ok'] for s in servers)
        payload={'schema_version':1,'last_attempted_refresh':now,'refresh_ok':complete,
                 'last_successful_refresh':now if complete else self.snapshot.get('last_successful_refresh'),
                 'servers':servers,'events':sorted(events,key=lambda e:(e['start_at'],e['server_id'],e['id']))}
        await asyncio.to_thread(atomic_snapshot,self.path,payload)
        self.snapshot=payload
        return {'servers':len(servers),'events':len(events),'complete':complete,
                'excluded_restricted':excluded,'excluded_unverified':unverified}
