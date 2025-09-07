#!/usr/bin/env python3
"""
Test script to verify cookie functionality in the worker
"""

import os
import subprocess
import sys

def test_worker_cookie_logic():
    """Test if the worker can handle cookies properly"""
    
    print("🧪 Testing yt-dlp worker cookie functionality")
    print("=" * 50)
    
    # Test 1: Check if cookies file exists
    cookies_file = "cookies.txt"
    if os.path.exists(cookies_file):
        print(f"✅ Cookies file found: {cookies_file}")
        
        # Test with cookies file
        cmd = [
            'yt-dlp',
            '--cookies', cookies_file,
            '--simulate',
            '--print', 'title',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        ]
        
        print(f"Testing command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Cookie test successful!")
                print(f"Video title: {result.stdout.strip()}")
                return True
            else:
                print(f"❌ Cookie test failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Test timed out")
            return False
        except Exception as e:
            print(f"❌ Test error: {str(e)}")
            return False
    else:
        print(f"⚠️  Cookies file not found: {cookies_file}")
        
        # Test fallback to browser cookies
        print("Testing fallback to browser cookies...")
        
        cmd = [
            'yt-dlp',
            '--cookies-from-browser', 'chrome',
            '--simulate',
            '--print', 'title',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        ]
        
        print(f"Testing command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Browser cookie test successful!")
                print(f"Video title: {result.stdout.strip()}")
                return True
            else:
                print(f"❌ Browser cookie test failed: {result.stderr}")
                print("\n💡 You need to export cookies manually.")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Test timed out")
            return False
        except Exception as e:
            print(f"❌ Test error: {str(e)}")
            return False

def main():
    success = test_worker_cookie_logic()
    
    if not success:
        print("\n" + "=" * 50)
        print("📋 NEXT STEPS:")
        print("=" * 50)
        print("1. Export cookies from your browser:")
        print("   - Install 'Get cookies.txt LOCALLY' Chrome extension")
        print("   - Go to YouTube (logged in)")
        print("   - Click extension → Export cookies")
        print("   - Save as 'cookies.txt' in this directory")
        print("\n2. Or use the cookies_template.txt file:")
        print("   - Copy cookies manually from browser dev tools")
        print("   - Fill in the template")
        print("   - Rename to cookies.txt")
        print("\n3. Run this test again to verify")
        
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)