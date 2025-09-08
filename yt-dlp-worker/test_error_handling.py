#!/usr/bin/env python3
"""
Test script for enhanced error handling and recovery mechanisms
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# Add the worker module to the path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from worker import DownloadWorker, ProgressState
except ImportError as e:
    print(f"Error importing worker module: {e}")
    print("This test requires the worker.py file to be in the same directory")
    sys.exit(1)

class TestErrorHandling(unittest.TestCase):
    """Test cases for enhanced error handling and recovery"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.worker = DownloadWorker()
        self.client_id = "test_client_123"
    
    def test_progress_parsing_failure_handling(self):
        """Test progress parsing failure handling and recovery"""
        # Test that parsing failures are tracked
        self.worker._handle_progress_parsing_failure(
            self.client_id, "invalid line", "ValueError", "Invalid progress"
        )
        
        # Check that failure count is tracked
        self.assertTrue(hasattr(self.worker, '_parsing_failure_counts'))
        failure_key = f"{self.client_id}_parsing_failures"
        self.assertEqual(self.worker._parsing_failure_counts[failure_key], 1)
        
        # Test that multiple failures activate fallback
        for i in range(3):
            self.worker._handle_progress_parsing_failure(
                self.client_id, f"invalid line {i}", "ValueError", "Invalid progress"
            )
        
        # Check that fallback is activated after multiple failures
        progress_state = self.worker.get_or_create_progress_state(self.client_id)
        self.assertTrue(progress_state.fallback_active)
    
    def test_websocket_failure_tracking(self):
        """Test WebSocket failure tracking and degraded mode"""
        # Mock the requests.post to simulate failures
        with patch('requests.post') as mock_post:
            mock_post.side_effect = Exception("Connection failed")
            
            # Test WebSocket failure handling
            payload = {"test": "data"}
            result = self.worker._send_progress_request(
                self.client_id, payload, datetime.now()
            )
            
            # Should return False on failure
            self.assertFalse(result)
            
            # Check that failure is tracked
            self.assertTrue(hasattr(self.worker, '_websocket_failure_tracking'))
            client_key = f"{self.client_id}_websocket_failures"
            failure_info = self.worker._websocket_failure_tracking.get(client_key, {})
            self.assertGreater(failure_info.get('consecutive_failures', 0), 0)
    
    def test_websocket_degraded_mode(self):
        """Test WebSocket degraded mode activation"""
        # Simulate multiple WebSocket failures
        self.worker._handle_websocket_failure(
            self.client_id, "connection", "Connection failed"
        )
        self.worker._handle_websocket_failure(
            self.client_id, "connection", "Connection failed"
        )
        self.worker._handle_websocket_failure(
            self.client_id, "connection", "Connection failed"
        )
        
        # Check that degraded mode is activated
        self.assertTrue(self.worker._is_websocket_degraded(self.client_id))
    
    def test_stall_detection(self):
        """Test download stall detection"""
        # Create a mock process
        mock_process = Mock()
        mock_process.poll.return_value = None  # Process is still running
        
        # Test stall detection with no progress
        is_stalled, reason = self.worker._detect_download_stall(self.client_id, mock_process)
        
        # Should not be stalled initially
        self.assertFalse(is_stalled)
        self.assertEqual(reason, "active")
        
        # Simulate time passing without progress
        if hasattr(self.worker, '_stall_detection'):
            stall_key = f"{self.client_id}_stall_detection"
            if stall_key in self.worker._stall_detection:
                # Manually set last progress change to simulate stall
                self.worker._stall_detection[stall_key]['last_progress_change'] = datetime.now() - timedelta(seconds=30)
                
                # Test stall detection again
                is_stalled, reason = self.worker._detect_download_stall(self.client_id, mock_process)
                self.assertTrue(is_stalled)
                self.assertIn("no_progress", reason)
    
    def test_cleanup_functionality(self):
        """Test comprehensive cleanup functionality"""
        # Set up some tracking data
        self.worker._handle_progress_parsing_failure(
            self.client_id, "test", "ValueError", "test error"
        )
        self.worker._handle_websocket_failure(
            self.client_id, "connection", "test failure"
        )
        
        # Create progress state
        progress_state = self.worker.get_or_create_progress_state(self.client_id)
        
        # Perform cleanup
        self.worker.cleanup_progress_state(self.client_id)
        
        # Verify cleanup
        self.assertNotIn(self.client_id, self.worker._progress_states)
        
        # Check that error tracking is cleaned up
        if hasattr(self.worker, '_parsing_failure_counts'):
            failure_key = f"{self.client_id}_parsing_failures"
            self.assertEqual(self.worker._parsing_failure_counts.get(failure_key, 0), 0)
    
    def test_error_statistics_logging(self):
        """Test error handling statistics logging"""
        # Set up some error data
        self.worker._handle_progress_parsing_failure(
            self.client_id, "test", "ValueError", "test error"
        )
        self.worker._handle_websocket_failure(
            self.client_id, "connection", "test failure"
        )
        
        # Test that statistics can be logged without errors
        try:
            self.worker.log_error_handling_statistics(self.client_id)
            self.worker.log_error_handling_statistics()  # Global stats
        except Exception as e:
            self.fail(f"Error statistics logging failed: {e}")

def main():
    """Run the error handling tests"""
    print("Testing enhanced error handling and recovery mechanisms...")
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestErrorHandling)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    if result.wasSuccessful():
        print("\n✅ All error handling tests passed!")
        return 0
    else:
        print(f"\n❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return 1

if __name__ == "__main__":
    sys.exit(main())