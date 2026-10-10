import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cwt_macro.config import load_env_file, require_live_credentials, setup_status
from cwt_macro.cli import main


class CredentialTests(unittest.TestCase):
    def test_local_file_loading_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'APIFY_TOKEN':'ENV_TEST'},clear=True):
            path=Path(folder)/'.env'
            path.write_text('# private\nAPIFY_TOKEN=FILE_TEST\nexport TAVILY_API_KEY="NEWS_TEST"\n')
            self.assertTrue(load_env_file(path))
            self.assertEqual(os.environ['APIFY_TOKEN'],'ENV_TEST')
            self.assertEqual(os.environ['TAVILY_API_KEY'],'NEWS_TEST')
            self.assertTrue(setup_status()['ready_to_attempt_live_ingestion'])
            self.assertFalse(setup_status()['authentication_verified'])
            self.assertNotIn('NEWS_TEST',str(setup_status()))

    def test_missing_credentials_stop_before_any_apify_call(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'APIFY_TOKEN':'TEST_ONLY'},clear=True):
            path=Path(folder)/'.env';path.write_text('TAVILY_API_KEY=\n')
            with patch('sys.argv',['cwt-macro','--env-file',str(path),'ingest-live','--as-of','2026-10-10']), \
                 patch('cwt_macro.ingest.fetch_calendar') as calendar, \
                 patch('cwt_macro.ingest.fetch_news') as news, \
                 patch('sys.stderr'):
                with self.assertRaises(SystemExit) as result: main()
                self.assertEqual(result.exception.code,2)
                calendar.assert_not_called();news.assert_not_called()

    def test_invalid_file_is_atomic_and_secrets_are_not_in_errors(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{},clear=True):
            path=Path(folder)/'.env'
            path.write_text('APIFY_TOKEN=TEST_SECRET\nTAVILY_API_KEY="UNCLOSED_SECRET\n')
            with self.assertRaises(ValueError) as result: load_env_file(path)
            self.assertNotIn('SECRET',str(result.exception))
            self.assertNotIn('APIFY_TOKEN',os.environ)

    def test_blank_and_missing_files_are_not_authentication(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{},clear=True):
            path=Path(folder)/'.env'
            self.assertFalse(load_env_file(path))
            with self.assertRaises(ValueError): load_env_file(path,required=True)
            self.assertEqual(setup_status()['missing_settings'],['APIFY_TOKEN','TAVILY_API_KEY'])
            with self.assertRaises(ValueError): require_live_credentials()


if __name__=='__main__': unittest.main()
