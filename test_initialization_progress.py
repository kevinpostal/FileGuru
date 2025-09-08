#!/usr/bin/env python3
"""
Test script to verify enhanced initialization progress simulation
"""

import sys
import os
import time
import json
from datetime import datetime

# Add the worker directory to the path
sys.path.append('yt-dlp-worker')

# Import the worker classes
from worker import FallbackProgressGenerator, ProgressState

def test_initialization_progress():
    """Test the enhanced initialization progress simulation"""
    print("Testing Enhanced Initialization Progress Simulation")
    print("=" * 60)
    
    # Create a progress generator for testing
    client_id = "test_client_123"
    estimated_duration = 300  # 5 minutes
    
    print(f"Creating progress generator for client: {client_id}")
    print(f"Estimated duration: {estimated_duration} seconds")
    print()
    
    # Create fallback progress generator
    generator = FallbackProgressGenerator(client_id, estimated_duration)
    
    # Create progress state
    progress_state = ProgressState(client_id)
    progress_state.activate_fallback()
    progress_state.fallback_generator = generator
    
    print("Simulating initialization phase progress updates:")
    print("Time(s) | Progress | Phase | Message")
    print("-" * 50)
    
    start_time = time.time()
    
    # Simulate progress updates for the first 30 seconds (initialization phase)
    for i in range(30):
        elapsed = time.time() - start_time
        
        # Update progress
        current_progress = generator.update_progress()
        metadata = generator.get_progress_metadata()
        
        # Generate message based on progress
        if current_progress < 3:
            message = f"Starting download... {current_progress:.1f}%"
        elif current_progress < 8:
            message = f"Connecting to server... {current_progress:.1f}%"
        elif current_progress < 12:
            message = f"Analyzing video... {current_progress:.1f}%"
        elif current_progress < 15:
            message = f"Preparing download... {current_progress:.1f}%"
        else:
            message = f"Downloading... {current_progress:.1f}% (estimated)"
        
        print(f"{elapsed:6.1f} | {current_progress:7.1f}% | {metadata['current_phase']:13} | {message}")
        
        # Sleep for 1 second to simulate real-time updates
        time.sleep(1)
    
    print()
    print("Test completed! The initialization phase should show:")
    print("1. Immediate progress starting from 0%")
    print("2. Rapid initial progress in the first few seconds")
    print("3. Engaging messages that change as progress increases")
    print("4. Smooth transition through the initialization phase")

def test_progress_state_management():
    """Test the progress state management system"""
    print("\nTesting Progress State Management")
    print("=" * 40)
    
    client_id = "test_state_client"
    progress_state = ProgressState(client_id)
    
    print(f"Created progress state for client: {client_id}")
    print(f"Initial phase: {progress_state.current_phase}")
    print(f"Fallback active: {progress_state.fallback_active}")
    
    # Activate fallback
    progress_state.activate_fallback()
    print(f"After activating fallback:")
    print(f"Fallback active: {progress_state.fallback_active}")
    print(f"Progress type: {progress_state.progress_type}")
    
    # Test progress updates
    for i in range(5):
        progress = progress_state.get_current_progress()
        metadata = progress_state.get_progress_metadata()
        print(f"Update {i+1}: {progress:.1f}% - Phase: {metadata['current_phase']}")
        time.sleep(0.5)

if __name__ == "__main__":
    try:
        test_initialization_progress()
        test_progress_state_management()
        print("\n✅ All tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()