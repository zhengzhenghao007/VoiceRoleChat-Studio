"""Versioned conversation persistence without any generation or model loading."""
import hashlib,json,sqlite3,sys,tempfile,unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from schemas.session import CharacterSnapshot,SessionCreate,SessionRename,TurnInput
from services.session_service import SessionService,SessionError

class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'sessions';self.store=SessionService(self.root)
        self.character=CharacterSnapshot(name='Role',revision=3,system_prompt='Be concise',reply_language='Japanese',translation_language='Chinese')
    def create(self):return self.store.create(SessionCreate(character_id='a'*32,title='会话'),self.character)
    def turn(self,revision=1,request_id=None):
        return TurnInput(expected_revision=revision,request_id=request_id or uuid4().hex,user_text='你好',assistant_text='fixture reply',model='fixture')
    def test_absent_reads_and_restart_snapshot_persistence(self):
        self.assertEqual(self.store.list().items,[]);self.assertFalse(self.root.exists())
        session=self.create();self.character.name='Changed'
        restored=SessionService(self.root).get(session.id)
        self.assertEqual(restored.character.name,'Role');self.assertEqual(restored.revision,1)
        self.assertEqual(self.store.messages(session.id),[])
        renamed=self.store.rename(session.id,SessionRename(title='new',expected_revision=1))
        self.assertEqual(renamed.revision,2);self.assertEqual(self.store.list().items[0].title,'new')
        with self.assertRaises(SessionError) as conflict:self.store.rename(session.id,SessionRename(title='stale',expected_revision=1))
        self.assertEqual(conflict.exception.code,'revision_conflict')
    def test_atomic_pair_idempotency_and_request_conflicts(self):
        session=self.create();turn=self.turn();result=self.store.append_turn(session.id,turn)
        self.assertEqual(result.revision,2);self.assertEqual(result.message_count,2)
        messages=self.store.messages(session.id);self.assertEqual([m.role for m in messages],['user','assistant'])
        self.assertEqual([m.content for m in messages],['你好','fixture reply'])
        self.assertEqual(SessionService(self.root).append_turn(session.id,turn).revision,2)
        self.store.append_turn(session.id,self.turn(revision=2))
        self.assertEqual(self.store.append_turn(session.id,turn).revision,2,'Retry must return original receipt after later commits')
        with self.assertRaises(SessionError) as conflict:self.store.append_turn(session.id,turn.model_copy(update={'user_text':'other'}))
        self.assertEqual(conflict.exception.code,'request_conflict')
        with self.assertRaises(SessionError):self.store.append_turn(session.id,self.turn(revision=1))
        self.assertEqual(len(self.store.messages(session.id)),4)
    def test_sql_failure_rolls_back_pair_and_revision(self):
        session=self.create()
        with patch.object(self.store,'_bump',side_effect=sqlite3.OperationalError('injected')):
            with self.assertRaises(SessionError):self.store.append_turn(session.id,self.turn())
        self.assertEqual(self.store.get(session.id).revision,1);self.assertEqual(self.store.messages(session.id),[])
    def test_concurrent_writers_cannot_commit_two_same_revision(self):
        session=self.create()
        def append(_):
            try:SessionService(self.root).append_turn(session.id,self.turn());return 'ok'
            except SessionError as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:outcomes=list(executor.map(append,range(2)))
        self.assertEqual(sorted(outcomes),['ok','revision_conflict']);self.assertEqual(len(self.store.messages(session.id)),2)
    def test_future_database_and_session_preserved(self):
        self.root.mkdir();path=self.store.path
        with closing(sqlite3.connect(path)) as connection:connection.execute('PRAGMA user_version=99');connection.commit()
        before=path.read_bytes()
        with self.assertRaises(SessionError) as future:self.store.list()
        self.assertEqual(future.exception.code,'schema_unsupported');self.assertEqual(path.read_bytes(),before)
        other=SessionService(Path(self.temp.name)/'other');session=other.create(SessionCreate(character_id='a'*32,title='x'),self.character)
        with closing(sqlite3.connect(other.path)) as connection:connection.execute('UPDATE sessions SET schema_version=2 WHERE id=?',(session.id,));connection.commit()
        before=other.path.read_bytes()
        with self.assertRaises(SessionError) as future:other.get(session.id)
        self.assertEqual(future.exception.code,'schema_unsupported');self.assertEqual(other.path.read_bytes(),before)
    def test_corrupt_database_invalid_identity_and_capacity(self):
        for identity in ('../outside','b'*32):
            with self.assertRaises(SessionError) as missing:self.store.get(identity)
            self.assertEqual(missing.exception.status_code,404)
        self.store.max_sessions=1;session=self.create()
        with self.assertRaises(SessionError) as full:self.create()
        self.assertEqual(full.exception.status_code,429)
        self.store.max_turns=1;self.store.append_turn(session.id,self.turn())
        with self.assertRaises(SessionError) as full:self.store.append_turn(session.id,self.turn(revision=2))
        self.assertEqual(full.exception.status_code,429)
        bad=SessionService(Path(self.temp.name)/'bad');bad.root.mkdir();bad.path.write_bytes(b'not sqlite')
        before=bad.path.read_bytes()
        with self.assertRaises(SessionError):bad.list()
        self.assertEqual(bad.path.read_bytes(),before)
    def test_strict_turn_and_snapshot_validation(self):
        from pydantic import ValidationError
        for values in ({'expected_revision':True},{'user_text':'x'*8001},{'assistant_text':'x'*16001},{'request_id':'../x'},{'unknown':'x'}):
            with self.subTest(values=tuple(values)),self.assertRaises(ValidationError):TurnInput(**{**self.turn().model_dump(),**values})
        session=self.create()
        with closing(sqlite3.connect(self.store.path)) as connection:connection.execute('UPDATE sessions SET character_snapshot=? WHERE id=?',('{"unknown":1}',session.id));connection.commit()
        with self.assertRaises(SessionError) as invalid:self.store.get(session.id)
        self.assertEqual(invalid.exception.code,'invalid_record')
    def test_database_hardlink_and_directory_escape_refused(self):
        import os
        session=self.create();outside=Path(self.temp.name)/'alias.sqlite3';os.link(self.store.path,outside)
        with self.assertRaises(SessionError):self.store.get(session.id)
        with patch.object(Path,'resolve',return_value=Path(self.temp.name)/'elsewhere'):
            with self.assertRaises(SessionError):SessionService(self.root).list()
        file_root=Path(self.temp.name)/'regular-file';file_root.write_text('keep')
        with self.assertRaises(SessionError):SessionService(file_root).list()
        self.assertEqual(file_root.read_text(),'keep')

if __name__=='__main__':unittest.main()
