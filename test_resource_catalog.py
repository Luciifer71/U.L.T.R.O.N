import tempfile
import unittest
from pathlib import Path

from ultron_resources.catalog import PathPolicy, ResourceCatalog, ResourceError, AmbiguousResource, AccessDenied
from ultron_resources.service import ResourceService, PlatformAdapter


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'files'; self.root.mkdir()
        self.catalog = ResourceCatalog(self.base / 'catalog.db', PathPolicy([self.root]))

    def file(self, name, data='test'):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(data)
        return path

    def test_name_resolution_supports_spaces_and_game_numbers(self):
        file = self.file('games/ForzaHorizon6.exe')
        self.catalog.index(self.root)
        self.assertEqual(self.catalog.resolve('Forza Horizon 6').path, str(file))
        with self.assertRaises(ResourceError): self.catalog.resolve('Forza Horizon 5')

    def test_document_stem_is_resolved(self):
        path = self.file('report.txt')
        self.catalog.index(self.root)
        self.assertEqual(self.catalog.resolve('report').path, str(path))

    def test_duplicate_names_require_clarification(self):
        self.file('one/report.txt'); self.file('two/report.txt')
        self.catalog.index(self.root)
        with self.assertRaises(AmbiguousResource) as result: self.catalog.resolve('report')
        self.assertEqual(len(result.exception.candidates), 2)
        self.assertEqual(len(self.catalog.search('report', root=self.root/'one')), 1)

    def test_extension_disambiguates_documents(self):
        txt = self.file('report.txt'); self.file('report.pdf')
        self.catalog.index(self.root)
        with self.assertRaises(AmbiguousResource): self.catalog.resolve('report')
        self.assertEqual(self.catalog.resolve('report.txt').path, str(txt))
        with self.assertRaises(ResourceError): self.catalog.resolve('report.docx')

    def test_deleted_results_are_not_returned(self):
        file = self.file('deleted.txt'); self.catalog.index(self.root); file.unlink()
        self.assertEqual(self.catalog.search('deleted'), [])

    def test_complete_refresh_prunes_deleted_rows(self):
        file = self.file('old.txt'); self.catalog.index(self.root); file.unlink(); self.catalog.index(self.root)
        with self.catalog.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM resources WHERE name=?', ('old.txt',)).fetchone()[0], 0)

    def test_incomplete_scan_does_not_prune_existing_rows(self):
        self.file('old.txt'); self.catalog.index(self.root)
        result = self.catalog.index(self.root, max_entries=1)
        self.assertFalse(result['complete'])
        self.assertEqual(len(self.catalog.search('old')), 1)

    def test_outside_root_is_denied(self):
        external=self.base/'outside.txt'; external.write_text('private')
        with self.assertRaises(AccessDenied): self.catalog.resolve(str(external))

    def test_credentials_not_indexed(self):
        self.file('.ssh/id_rsa'); self.file('.env'); self.file('AppData/Vault/secret.txt')
        result=self.catalog.index(self.root)
        self.assertGreater(result['protected_skipped'], 0)
        self.assertEqual(self.catalog.search('id_rsa'), [])
        self.assertEqual(self.catalog.search('secret'), [])

    def test_symlink_escape_is_denied(self):
        outside=self.base/'external'; outside.mkdir(); (outside/'secret.txt').write_text('private')
        link=self.root/'shortcut'
        try: link.symlink_to(outside, target_is_directory=True)
        except OSError: self.skipTest('Host does not permit creation of symlinks.')
        self.catalog.index(self.root)
        self.assertEqual(self.catalog.search('secret'), [])
        with self.assertRaises(AccessDenied): self.catalog.resolve(str(link/'secret.txt'))

    def test_unicode_names_are_preserved(self):
        path=self.file('परीक्षा.txt'); self.catalog.index(self.root)
        self.assertEqual(self.catalog.resolve('परीक्षा').path,str(path))

    def test_diacritics_do_not_substitute_another_resource(self):
        self.file('किताब.txt'); self.catalog.index(self.root)
        with self.assertRaises(ResourceError): self.catalog.resolve('कताब')

    def test_read_is_bounded_and_utf8_only(self):
        path=self.file('notes.txt','hello')
        service=ResourceService(self.catalog)
        self.assertEqual(service.read_text(str(path)), 'hello')
        with self.assertRaises(ResourceError): service.read_text(str(path),max_bytes=2)

    def test_script_runs_in_its_directory_with_literal_arguments(self):
        path=self.file('script.py', 'import os,sys; print(os.getcwd()); print(sys.argv[1])')
        result=ResourceService(self.catalog).run_script(str(path),arguments=['a; echo unrequested'])
        self.assertTrue(result.success)
        self.assertIn(str(self.root),result.stdout)
        self.assertIn('a; echo unrequested',result.stdout)

    def test_script_nonzero_exit_is_failure(self):
        path=self.file('failure.py','raise SystemExit(7)')
        result=ResourceService(self.catalog).run_script(str(path))
        self.assertFalse(result.success); self.assertEqual(result.exit_code,7)

    def test_script_timeout_is_reported(self):
        path=self.file('slow.py','import time; time.sleep(10)')
        result=ResourceService(self.catalog).run_script(str(path),timeout=.1)
        self.assertFalse(result.success); self.assertIn('timed out',result.message)

    def test_open_does_not_execute_scripts(self):
        path=self.file('script.py','raise RuntimeError("must not run")')
        with self.assertRaises(ResourceError): ResourceService(self.catalog).open(str(path))

    def test_arguments_are_structured(self):
        with self.assertRaises(ResourceError): ResourceService.arguments('echo command')

    def test_game_folder_and_executable_do_not_create_false_launch_ambiguity(self):
        from unittest.mock import Mock
        path = self.file('Example/Example.exe')
        self.catalog.index(self.root)
        adapter = Mock(launch=Mock(return_value=12))
        outcome = ResourceService(self.catalog, adapter).launch('Example')
        self.assertTrue(outcome.success)
        adapter.launch.assert_called_once_with(path, [])

    def test_explicit_path_obeys_requested_scope(self):
        path = self.file('one/report.txt'); self.file('two/other.txt')
        with self.assertRaises(AccessDenied): self.catalog.resolve(str(path), root=self.root/'two')

    def test_many_partial_matches_do_not_hide_exact_duplicates(self):
        for index in range(1050):
            self.file(f'partial{index}/report-extra.txt')
        self.file('one/report.txt'); self.file('two/report.txt')
        self.catalog.index(self.root)
        with self.assertRaises(AmbiguousResource): self.catalog.resolve('report')

    def test_scoped_search_is_filtered_before_truncation(self):
        for index in range(1020):
            self.file(f'other{index}/report.txt')
        wanted = self.file('zzchosen/report.txt')
        self.catalog.index(self.root)
        self.assertEqual(self.catalog.resolve('report', root=self.root/'zzchosen').path, str(wanted))

    def test_invalid_config_is_rejected(self):
        from unittest.mock import patch
        from ultron_resources.config import create_service
        for value in ['[]', '{"roots":"C:\\\\"}', '{"roots":["relative"]}', '{"roots":[]}']:
            config = self.base / 'settings.json'; config.write_text(value)
            with patch('ultron_resources.config.data_directory', return_value=self.base), patch.dict('os.environ', {'ULTRON_RESOURCE_CONFIG': str(config)}):
                with self.assertRaises((ResourceError, ValueError)): create_service()


class AdapterTests(unittest.TestCase):
    def test_macos_application_bundle_uses_absolute_launcher(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch('ultron_resources.service.subprocess.run',return_value=SimpleNamespace(returncode=0,stderr='')) as run:
            PlatformAdapter('darwin').launch(Path('/Applications/Example.app'), ['literal;value'])
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open',str(Path('/Applications/Example.app')),'--args','literal;value'])

    def test_windows_game_launch_uses_game_directory_and_literal_arguments(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        path = Path('/games/Game.exe')
        with patch('ultron_resources.service.subprocess.Popen',return_value=SimpleNamespace(pid=13)) as popen:
            self.assertEqual(PlatformAdapter('win32').launch(path, ['literal;value']), 13)
            self.assertEqual(popen.call_args.args[0], [str(path), 'literal;value'])
            self.assertEqual(popen.call_args.kwargs['cwd'], path.parent)
            self.assertFalse(popen.call_args.kwargs['shell'])

    def test_macos_editor_uses_literal_argv(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch('ultron_resources.service.subprocess.run',return_value=SimpleNamespace(returncode=0,stderr='')) as run:
            PlatformAdapter('darwin').open(Path('/tmp/a; touch unwanted.txt'),'TextEdit')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open','-a','TextEdit',str(Path('/tmp/a; touch unwanted.txt'))])
            self.assertFalse(run.call_args.kwargs['shell'])

    def test_windows_editor_uses_absolute_system_executable(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        with patch('ultron_resources.service.subprocess.Popen',return_value=SimpleNamespace(pid=12)) as popen:
            self.assertEqual(PlatformAdapter('win32').open(Path('/tmp/notes.txt'),'Notepad'),12)
            self.assertEqual(popen.call_args.args[0][-1], str(Path('/tmp/notes.txt')))
            self.assertFalse(popen.call_args.kwargs['shell'])

    def test_unsupported_platform_does_not_claim_success(self):
        with self.assertRaises(ResourceError): PlatformAdapter('linux').open(Path('/tmp/example'))

    def test_file_dispatch_is_not_claimed_as_verified(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'notes.txt';path.write_text('hello')
            service=ResourceService(ResourceCatalog(Path(folder)/'db',PathPolicy([folder])),Mock(open=Mock(return_value=None)))
            self.assertEqual(service.open(str(path)).state,'dispatched')


class OutputBoundTests(unittest.TestCase):
    def test_large_stdout_is_drained_and_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); script=root/'large.py'; script.write_text('print("x" * 100000)')
            service=ResourceService(ResourceCatalog(root/'db',PathPolicy([root])))
            result=service.run_script(str(script))
            self.assertTrue(result.success)
            self.assertEqual(len(result.stdout),20000)
            self.assertTrue(result.output_truncated)
