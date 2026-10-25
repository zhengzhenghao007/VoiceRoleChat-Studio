"""Independent SQLite conversations; transactions contain no model or network work."""
from contextlib import contextmanager,closing
from datetime import datetime,timezone
import json,re,sqlite3,stat
from pathlib import Path
from uuid import uuid4
from pydantic import ValidationError
from schemas.session import (CharacterSnapshot,SessionCreate,SessionRename,TurnInput,
    SessionRecord,SessionSummary,SessionPage,MessageRecord,TurnReceipt)


class SessionError(RuntimeError):
    def __init__(self,code,status_code=503):
        self.code=code;self.status_code=status_code;super().__init__(code)


def now():return datetime.now(timezone.utc).isoformat()


class SessionService:
    max_sessions=1000
    max_turns=100

    def __init__(self,directory):
        self.root=Path(directory).absolute();self.path=self.root/'studio.sqlite3'

    def _check(self):
        try:
            for path in (self.root,*self.root.parents,self.path,
                         Path(str(self.path)+'-journal'),Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')):
                if path.resolve()!=path:raise ValueError()
                if path.exists():
                    info=path.stat()
                    if getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):raise ValueError()
                    if path in (self.root,*self.root.parents) and not stat.S_ISDIR(info.st_mode):raise ValueError()
                    if path not in (self.root,*self.root.parents) and (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1):raise ValueError()
        except (OSError,RuntimeError,ValueError):raise SessionError('storage_unavailable') from None

    @contextmanager
    def _connection(self,*,write=False,create=False):
        connection=None
        try:
            self._check()
            new_store=not self.path.exists()
            if new_store:
                if not create:raise SessionError('session_not_found',404)
                self.root.mkdir(parents=True,exist_ok=True);self._check()
            elif write:
                # Probe unknown existing stores without write access or hot-journal recovery.
                with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as probe:
                    version=probe.execute('PRAGMA user_version').fetchone()[0]
                    if version!=1 and (version!=0 or not create or probe.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone()):raise SessionError('schema_unsupported',409)
            # mode=rw on existing stores prevents silent recreation after removal.
            mode='rw' if write else 'ro'
            connection=sqlite3.connect(self.path if new_store else self.path.as_uri()+'?mode='+mode,uri=not new_store,timeout=2,isolation_level=None)
            connection.row_factory=sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            version=connection.execute('PRAGMA user_version').fetchone()[0]
            if version!=1:
                if version!=0 or not create:raise SessionError('schema_unsupported',409)
                if connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():raise SessionError('schema_unsupported',409)
                connection.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,revision INTEGER NOT NULL,title TEXT NOT NULL,character_id TEXT NOT NULL,character_snapshot TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
                connection.execute('CREATE TABLE turns(session_id TEXT NOT NULL REFERENCES sessions(id),request_id TEXT NOT NULL,seq INTEGER NOT NULL,revision INTEGER NOT NULL,user_id TEXT NOT NULL,assistant_id TEXT NOT NULL,user_text TEXT NOT NULL,assistant_text TEXT NOT NULL,model TEXT,created_at TEXT NOT NULL,PRIMARY KEY(session_id,request_id),UNIQUE(session_id,seq))')
                connection.execute('PRAGMA user_version=1')
            yield connection
            if write:connection.commit()
        except (sqlite3.Error,OSError):raise SessionError('storage_unavailable') from None
        finally:
            if connection is not None:
                try:
                    if connection.in_transaction:connection.rollback()
                finally:connection.close()

    def _identity(self,identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):raise SessionError('session_not_found',404)

    def _read(self,connection,identity):
        row=connection.execute('SELECT *, (SELECT count(*)*2 FROM turns WHERE session_id=sessions.id) AS message_count FROM sessions WHERE id=?',(identity,)).fetchone()
        if row is None:raise SessionError('session_not_found',404)
        if row['schema_version']!=1:raise SessionError('schema_unsupported',409)
        try:
            snapshot=row['character_snapshot']
            if not isinstance(snapshot,str) or len(snapshot.encode('utf8'))>65536:raise ValueError()
            return SessionRecord(id=row['id'],schema_version=row['schema_version'],revision=row['revision'],title=row['title'],character_id=row['character_id'],character=CharacterSnapshot.model_validate(json.loads(snapshot)),message_count=row['message_count'],created_at=row['created_at'],updated_at=row['updated_at'])
        except (ValueError,TypeError,ValidationError,RecursionError):raise SessionError('invalid_record',409) from None

    def create(self,request,snapshot):
        request=SessionCreate.model_validate(request.model_dump());snapshot=CharacterSnapshot.model_validate(snapshot.model_dump())
        identity=uuid4().hex;timestamp=now()
        with self._connection(write=True,create=True) as connection:
            if connection.execute('SELECT count(*) FROM sessions').fetchone()[0]>=self.max_sessions:raise SessionError('session_capacity',429)
            connection.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)',(identity,1,1,request.title,request.character_id,snapshot.model_dump_json(),timestamp,timestamp))
            result=self._read(connection,identity)
        return result

    def get(self,identity):
        self._identity(identity)
        with self._connection() as connection:return self._read(connection,identity)

    def list(self,limit=50,offset=0):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=10000:raise SessionError('invalid_page',422)
        self._check()
        if not self.path.exists():return SessionPage(items=[],total=0)
        with self._connection() as connection:
            total=connection.execute('SELECT count(*) FROM sessions').fetchone()[0]
            rows=connection.execute('SELECT id FROM sessions ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',(limit,offset)).fetchall()
            records=[self._read(connection,row['id']) for row in rows]
            items=[SessionSummary(id=item.id,title=item.title,character_id=item.character_id,character_name=item.character.name,revision=item.revision,message_count=item.message_count,created_at=item.created_at,updated_at=item.updated_at) for item in records]
            return SessionPage(items=items,total=total)

    def _bump(self,connection,identity):
        connection.execute('UPDATE sessions SET revision=revision+1,updated_at=? WHERE id=?',(now(),identity))

    def rename(self,identity,request):
        self._identity(identity);request=SessionRename.model_validate(request.model_dump())
        with self._connection(write=True) as connection:
            session=self._read(connection,identity)
            if request.expected_revision!=session.revision:raise SessionError('revision_conflict',409)
            connection.execute('UPDATE sessions SET title=? WHERE id=?',(request.title,identity));self._bump(connection,identity)
            result=self._read(connection,identity)
        return result

    def _receipt(self,row):
        try:return TurnReceipt(session_id=row['session_id'],request_id=row['request_id'],revision=row['revision'],message_count=row['seq']*2,user_message_id=row['user_id'],assistant_message_id=row['assistant_id'])
        except (ValueError,TypeError,ValidationError):raise SessionError('invalid_record',409) from None

    def append_turn(self,identity,request):
        self._identity(identity);request=TurnInput.model_validate(request.model_dump())
        with self._connection(write=True) as connection:
            session=self._read(connection,identity)
            old=connection.execute('SELECT * FROM turns WHERE session_id=? AND request_id=?',(identity,request.request_id)).fetchone()
            if old is not None:
                if (old['user_text'],old['assistant_text'],old['model'])!=(request.user_text,request.assistant_text,request.model):raise SessionError('request_conflict',409)
                return self._receipt(old)
            if request.expected_revision!=session.revision:raise SessionError('revision_conflict',409)
            count=session.message_count//2
            if count>=self.max_turns:raise SessionError('turn_capacity',429)
            connection.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,request.request_id,count+1,session.revision+1,uuid4().hex,uuid4().hex,request.user_text,request.assistant_text,request.model,now()))
            self._bump(connection,identity)
            row=connection.execute('SELECT * FROM turns WHERE session_id=? AND request_id=?',(identity,request.request_id)).fetchone();result=self._receipt(row)
        return result

    def messages(self,identity):
        self._identity(identity)
        with self._connection() as connection:
            session=self._read(connection,identity)
            rows=connection.execute('SELECT * FROM turns WHERE session_id=? ORDER BY seq LIMIT 101',(identity,)).fetchall()
            if len(rows)>100:raise SessionError('invalid_record',409)
            messages=[]
            try:
                if len(rows)*2!=session.message_count:raise ValueError()
                for index,row in enumerate(rows,1):
                    if type(row['seq']) is not int or row['seq']!=index or type(row['revision']) is not int or not 2<=row['revision']<=session.revision or row['user_id']==row['assistant_id']:raise ValueError()
                    TurnInput(request_id=row['request_id'],expected_revision=max(1,row['revision']-1),user_text=row['user_text'],assistant_text=row['assistant_text'],model=row['model'])
                    for role,key,text in (('user','user_id','user_text'),('assistant','assistant_id','assistant_text')):
                        messages.append(MessageRecord(id=row[key],request_id=row['request_id'],role=role,content=row[text],created_at=row['created_at'],model=row['model'] if role=='assistant' else None))
            except (ValueError,TypeError,ValidationError):raise SessionError('invalid_record',409) from None
            return messages
