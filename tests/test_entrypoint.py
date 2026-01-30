import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import datetime
import pytz

# Add the root directory to path to import entrypoint
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import entrypoint

class TestReleaseFreezeEnforcer(unittest.TestCase):

    def setUp(self):
        # Clear env vars before each test
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()
        
        # Mock GITHUB_OUTPUT and GITHUB_STEP_SUMMARY
        self.output_file = "github_output.txt"
        self.summary_file = "github_summary.txt"
        os.environ['GITHUB_OUTPUT'] = self.output_file
        os.environ['GITHUB_STEP_SUMMARY'] = self.summary_file
        
        # Ensure files exist and are empty
        open(self.output_file, 'w').close()
        open(self.summary_file, 'w').close()
    
    def tearDown(self):
        self.env_patcher.stop()
        if os.path.exists(self.output_file):
            os.remove(self.output_file)
        if os.path.exists(self.summary_file):
            os.remove(self.summary_file)

    def set_input(self, name, value):
        os.environ[f"INPUT_{name.upper()}"] = value

    def read_output(self):
        with open(self.output_file, 'r') as f:
            lines = f.readlines()
        outputs = {}
        for line in lines:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                outputs[key] = value
        return outputs

    def configure_mock_datetime(self, mock_datetime, target_dt):
        """Helper to configure the mock datetime module."""
        mock_datetime.datetime.now.return_value = target_dt
        # IMPORTANT: We must use the real timedelta, otherwise date math fails
        mock_datetime.timedelta = datetime.timedelta
        
    @patch('entrypoint.datetime')
    def test_no_freeze_configured(self, mock_datetime):
        # Mock time: 2023-01-01 12:00:00 UTC
        target_now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
        self.configure_mock_datetime(mock_datetime, target_now)
        
        self.set_input('environment', 'production')
        
        with self.assertRaises(SystemExit) as cm:
            entrypoint.main()
            
        self.assertEqual(cm.exception.code, 0)
        outputs = self.read_output()
        self.assertEqual(outputs['is_frozen'], 'false')
        self.assertEqual(outputs['decision'], 'ALLOW')
        self.assertEqual(outputs['window_type'], 'NONE')

    @patch('entrypoint.datetime')
    def test_fixed_window_frozen_block(self, mock_datetime):
        # Mock time: 2023-12-25 10:00:00 UTC
        target_now = datetime.datetime(2023, 12, 25, 10, 0, 0, tzinfo=pytz.utc)
        self.configure_mock_datetime(mock_datetime, target_now)
        
        self.set_input('environment', 'production')
        self.set_input('freeze_start', '2023-12-24T00:00')
        self.set_input('freeze_end', '2023-12-26T00:00')
        self.set_input('behavior', 'block')
        
        with self.assertRaises(SystemExit) as cm:
            entrypoint.main()
            
        self.assertEqual(cm.exception.code, 1)
        outputs = self.read_output()
        self.assertEqual(outputs['is_frozen'], 'true')
        self.assertEqual(outputs['decision'], 'BLOCK')
        self.assertEqual(outputs['window_type'], 'FIXED')

    @patch('entrypoint.datetime')
    def test_fixed_window_frozen_warn(self, mock_datetime):
        # Mock time: 2023-12-25 10:00:00 UTC
        target_now = datetime.datetime(2023, 12, 25, 10, 0, 0, tzinfo=pytz.utc)
        self.configure_mock_datetime(mock_datetime, target_now)
        
        self.set_input('environment', 'production')
        self.set_input('freeze_start', '2023-12-24T00:00')
        self.set_input('freeze_end', '2023-12-26T00:00')
        self.set_input('behavior', 'warn')
        
        with self.assertRaises(SystemExit) as cm:
            entrypoint.main()
            
        self.assertEqual(cm.exception.code, 0) # Warn should not fail
        outputs = self.read_output()
        self.assertEqual(outputs['is_frozen'], 'true')
        self.assertEqual(outputs['decision'], 'WARN')

    @patch('entrypoint.datetime')
    def test_recurring_window_weekend(self, mock_datetime):
        # RRULE: Every Saturday (SA)
        # Mock time: Saturday 2023-11-04 12:00:00 UTC
        target_now = datetime.datetime(2023, 11, 4, 12, 0, 0, tzinfo=pytz.utc)
        self.configure_mock_datetime(mock_datetime, target_now)
        
        self.set_input('environment', 'production')
        self.set_input('rrule', 'FREQ=WEEKLY;BYDAY=SA')
        self.set_input('duration_minutes', '1440') # 24 hours
        
        with self.assertRaises(SystemExit) as cm:
            entrypoint.main()
        
        # Should be frozen
        self.assertEqual(cm.exception.code, 1)
        outputs = self.read_output()
        self.assertEqual(outputs['is_frozen'], 'true')
        self.assertEqual(outputs['window_type'], 'RRULE')

    @patch('entrypoint.datetime')
    def test_recurring_window_not_frozen(self, mock_datetime):
        # RRULE: Every Saturday (SA)
        # Mock time: Friday 2023-11-03 12:00:00 UTC
        target_now = datetime.datetime(2023, 11, 3, 12, 0, 0, tzinfo=pytz.utc)
        self.configure_mock_datetime(mock_datetime, target_now)
        
        self.set_input('environment', 'production')
        self.set_input('rrule', 'FREQ=WEEKLY;BYDAY=SA')
        self.set_input('duration_minutes', '1440')
        
        with self.assertRaises(SystemExit) as cm:
            entrypoint.main()
        
        # Should NOT be frozen
        self.assertEqual(cm.exception.code, 0)
        outputs = self.read_output()
        self.assertEqual(outputs['is_frozen'], 'false')

    @patch('entrypoint.datetime')
    def test_override_by_actor(self, mock_datetime):
        # Mock time: 2023-12-25 10:00:00 UTC (Frozen)
        target_now = datetime.datetime(2023, 12, 25, 10, 0, 0, tzinfo=pytz.utc)
        self.configure_mock_datetime(mock_datetime, target_now)
        
        os.environ['GITHUB_ACTOR'] = 'maintainer_user'
        
        self.set_input('environment', 'production')
        self.set_input('freeze_start', '2023-12-24T00:00')
        self.set_input('freeze_end', '2023-12-26T00:00')
        self.set_input('allow_override_actor', 'maintainer_user')
        
        with self.assertRaises(SystemExit) as cm:
            entrypoint.main()
            
        # Should be ALLOWED because of override
        self.assertEqual(cm.exception.code, 0)
        outputs = self.read_output()
        self.assertEqual(outputs['is_frozen'], 'true')
        self.assertEqual(outputs['overridden'], 'true')
        self.assertEqual(outputs['decision'], 'ALLOW')
        self.assertIn('maintainer_user', outputs['override_reason'])

    @patch('entrypoint.datetime')
    def test_override_by_label(self, mock_datetime):
        # Mock time: 2023-12-25 10:00:00 UTC (Frozen)
        target_now = datetime.datetime(2023, 12, 25, 10, 0, 0, tzinfo=pytz.utc)
        self.configure_mock_datetime(mock_datetime, target_now)
        
        # Mock PR Event
        os.environ['GITHUB_EVENT_NAME'] = 'pull_request'
        event_path = 'event.json'
        with open(event_path, 'w') as f:
            f.write('{"pull_request": {"labels": [{"name": "hotfix-override"}, {"name": "bug"}]}}')
        os.environ['GITHUB_EVENT_PATH'] = event_path
        
        self.set_input('environment', 'production')
        self.set_input('freeze_start', '2023-12-24T00:00')
        self.set_input('freeze_end', '2023-12-26T00:00')
        self.set_input('allow_override_label', 'hotfix-override')
        
        try:
            with self.assertRaises(SystemExit) as cm:
                entrypoint.main()
            
            self.assertEqual(cm.exception.code, 0)
            outputs = self.read_output()
            self.assertEqual(outputs['is_frozen'], 'true')
            self.assertEqual(outputs['overridden'], 'true')
            self.assertEqual(outputs['decision'], 'ALLOW')
            self.assertIn('hotfix-override', outputs['override_reason'])
        finally:
            if os.path.exists(event_path):
                os.remove(event_path)

if __name__ == '__main__':
    unittest.main()
