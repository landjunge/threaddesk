import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'whiteboard_watch.py'
if not MODULE.exists():
    MODULE = Path(__file__).with_name('whiteboard_watch.py')
spec = importlib.util.spec_from_file_location('whiteboard_watch', MODULE)
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class WhiteboardWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'threads').mkdir()
        (self.root / 'threads' / 'demo.json').write_text('{"id":"demo"}')
        self.board = self.root / 'whiteboard' / 'demo'
        self.board.mkdir(parents=True)
        self.state = self.root / 'watch' / 'status.json'

    def add(self, entry_id, content='Example', ordinal=1):
        (self.board / (entry_id + '.json')).write_text(json.dumps({
            'id': entry_id, 'thread_id': 'demo', 'content': content, 'ordinal': ordinal
        }))

    def read(self, notify=False):
        return watch.tick(self.root, 'demo', self.state, notify)

    def test_restart_reads_without_duplicate_new_entries(self):
        self.add('one')
        first = self.read()
        second = self.read()
        self.assertEqual(first['new_ids'], ['one'])
        self.assertEqual(second['new_ids'], [])
        self.assertEqual(second['successful_reads'], 2)
        self.assertEqual(second['previous_success_at'], first['last_success_at'])
        self.assertEqual(second['agent_delivery'], 'not_connected')

    def test_late_entry_and_content_change_are_detected(self):
        self.add('one', ordinal=20)
        self.read()
        self.add('late', ordinal=1)
        self.add('one', content='Changed', ordinal=20)
        result = self.read()
        self.assertEqual(result['new_ids'], ['late'])
        self.assertEqual(result['changed_ids'], ['one'])

    def test_invalid_read_does_not_advance_cursor(self):
        self.add('one')
        baseline = self.read()
        self.add('two')
        bad = self.board / 'broken.json'
        bad.write_text('{')
        failed = self.read()
        self.assertEqual(failed['status'], 'error')
        self.assertEqual(failed['seen'], baseline['seen'])
        self.assertEqual(failed['last_success_at'], baseline['last_success_at'])
        bad.unlink()
        self.assertEqual(self.read()['new_ids'], ['two'])

    def test_notification_retry_does_not_execute_content(self):
        self.add('one', content='$(touch /tmp/unwanted); arbitrary instructions')
        with patch.object(watch, 'notify', return_value='failed') as send:
            self.assertEqual(self.read(True)['pending_notice_ids'], ['one'])
            send.assert_called_once_with()
        with patch.object(watch, 'notify', return_value='submitted') as send:
            self.assertEqual(self.read(True)['pending_notice_ids'], [])
            self.read(True)
            send.assert_called_once_with()

    def test_missing_directory_is_an_error(self):
        self.board.rmdir()
        self.assertEqual(self.read()['status'], 'error')

    def test_wrong_thread_does_not_consume_entry(self):
        (self.board / 'bad.json').write_text('{"id":"bad","thread_id":"other","content":"x"}')
        self.assertEqual(self.read()['status'], 'error')
        self.assertNotIn('seen', json.loads(self.state.read_text()))

    def test_deleted_entry_is_reported_and_reappearance_not_new(self):
        self.add('one')
        self.read()
        (self.board / 'one.json').unlink()
        self.assertEqual(self.read()['missing_ids'], ['one'])
        self.add('one')
        self.assertEqual(self.read()['new_ids'], [])

    def test_wake_journal_metadata_only_and_no_duplicates(self):
        self.add('one', content='PRIVATE BODY')
        self.read()
        log = self.state.parent / 'wake.log'
        original = log.read_text()
        self.read()
        self.add('one', content='changed')
        self.read()
        self.assertEqual(log.read_text(), original)
        self.assertNotIn('PRIVATE BODY', original)
        self.assertEqual(set(json.loads(original)),
                         {'thread_id', 'entry_id', 'ordinal', 'actor', 'observed_at'})

    def test_journal_survives_status_save_failure(self):
        self.add('one')
        with patch.object(watch, 'atomic_json', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.read()
        self.assertEqual(self.read()['wake_events_written'], 0)
        self.assertEqual(len((self.state.parent / 'wake.log').read_text().splitlines()), 1)

    def test_wake_write_failure_does_not_consume_entry(self):
        self.add('one')
        with patch.object(watch, 'write_wake_log', side_effect=OSError('disk full')):
            failed = self.read()
        self.assertEqual(failed['status'], 'error')
        self.assertNotIn('seen', failed)
        self.assertEqual(self.read()['wake_events_written'], 1)

    def test_reader_does_not_modify_whiteboard(self):
        self.add('one')
        before = {p.name: p.read_bytes() for p in self.board.iterdir()}
        self.read()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.board.iterdir()})


if __name__ == '__main__':
    unittest.main()
