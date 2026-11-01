import hashlib, sqlite3, threading
from pathlib import Path
DB_PATH = Path.home()/'.local/state/discord-bot/joke-ratings.sqlite3'
class JokeRatings:
 def __init__(self,path=DB_PATH):
  self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.lock=threading.RLock(); self.db=sqlite3.connect(self.path,check_same_thread=False); self.db.executescript('''CREATE TABLE IF NOT EXISTS jokes (joke_id TEXT PRIMARY KEY, text TEXT NOT NULL); CREATE TABLE IF NOT EXISTS posts (guild_id INTEGER NOT NULL,message_id INTEGER PRIMARY KEY,joke_id TEXT NOT NULL); CREATE TABLE IF NOT EXISTS votes (guild_id INTEGER NOT NULL,joke_id TEXT NOT NULL,user_id INTEGER NOT NULL,vote TEXT NOT NULL CHECK(vote IN ("funny","groan")),PRIMARY KEY(guild_id,joke_id,user_id)); CREATE TABLE IF NOT EXISTS usage (guild_id INTEGER NOT NULL,month TEXT NOT NULL,user_id INTEGER NOT NULL,interaction_id INTEGER NOT NULL UNIQUE,PRIMARY KEY(guild_id,month,user_id,interaction_id));''');
  if 'channel_id' not in {row[1] for row in self.db.execute('PRAGMA table_info(usage)')}: self.db.execute('ALTER TABLE usage ADD COLUMN channel_id INTEGER')
  self.db.commit()
 @staticmethod
 def joke_id(text): return hashlib.sha256(text.strip().encode()).hexdigest()[:32]
 def record_post(self,guild_id,message_id,text):
  jid=self.joke_id(text)
  with self.lock: self.db.execute('INSERT OR IGNORE INTO jokes(joke_id,text) VALUES(?,?)',(jid,text)); self.db.execute('INSERT OR REPLACE INTO posts(guild_id,message_id,joke_id) VALUES(?,?,?)',(guild_id,message_id,jid)); self.db.commit()
  return jid
 def vote(self,guild_id,joke_id,user_id,vote):
  with self.lock:
   old=self.db.execute('SELECT vote FROM votes WHERE guild_id=? AND joke_id=? AND user_id=?',(guild_id,joke_id,user_id)).fetchone()
   if old and old[0]==vote: self.db.execute('DELETE FROM votes WHERE guild_id=? AND joke_id=? AND user_id=?',(guild_id,joke_id,user_id))
   else: self.db.execute('INSERT OR REPLACE INTO votes VALUES(?,?,?,?)',(guild_id,joke_id,user_id,vote))
   self.db.commit(); return self.totals(guild_id,joke_id)
 def totals(self,guild_id,joke_id):
  rows=self.db.execute('SELECT vote,COUNT(*) FROM votes WHERE guild_id=? AND joke_id=? GROUP BY vote',(guild_id,joke_id)).fetchall(); d=dict(rows); return d.get('funny',0),d.get('groan',0)
 def leaderboard(self,guild_id,limit=5): return self.db.execute('SELECT j.text,SUM(v.vote="groan") groans,SUM(v.vote="funny") funny FROM votes v JOIN jokes j ON j.joke_id=v.joke_id WHERE v.guild_id=? GROUP BY v.joke_id ORDER BY groans DESC,funny DESC,j.text LIMIT ?',(guild_id,limit)).fetchall()
 def posts(self): return self.db.execute('SELECT guild_id,message_id,joke_id FROM posts').fetchall()
 def record_usage(self,guild_id,user_id,interaction_id,month,channel_id=None):
  with self.lock: self.db.execute('INSERT OR IGNORE INTO usage(guild_id,month,user_id,interaction_id,channel_id) VALUES(?,?,?,?,?)',(guild_id,month,user_id,interaction_id,channel_id)); self.db.commit()
 def usage_summary(self,guild_id,month):
  row=self.db.execute('SELECT COUNT(*),COUNT(DISTINCT user_id) FROM usage WHERE guild_id=? AND month=?',(guild_id,month)).fetchone(); return row or (0,0)
 def channel_usage(self,guild_id,channel_id,month): return self.db.execute('SELECT COUNT(*),COUNT(DISTINCT user_id) FROM usage WHERE guild_id=? AND channel_id=? AND month=?',(guild_id,channel_id,month)).fetchone() or (0,0)
 def top_users(self,guild_id,channel_id,month,limit=5): return self.db.execute('SELECT user_id,COUNT(*) FROM usage WHERE guild_id=? AND channel_id=? AND month=? GROUP BY user_id ORDER BY COUNT(*) DESC,user_id ASC LIMIT ?',(guild_id,channel_id,month,limit)).fetchall()
