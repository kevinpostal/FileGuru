#!/usr/bin/env python3
"""
Cookie export utility for yt-dlp worker.
This script helps export cookies from various browsers for use with yt-dlp.
"""

import os
import sys
import subprocess
import json
from pathlib import Path

def export_cookies_from_browser(browser='chrome', output_file='cookies.txt'):
    """
    Export cookies from browser using yt-dlp's built-in functionality
    """
    try:
        print(f"Attempting to export cookies from {browser}...")
        
        # Use yt-dlp to extract cookies from browser
        cmd = [
            'yt-dlp',
            '--cookies-from-browser', browser,
            '--print-to-file', 'cookies',
            output_file,
            '--no-download',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ'  # Test video
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ Cookies exported successfully to {output_file}")
            return True
        else:
            print(f"❌ Failed to export cookies: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error exporting cookies: {str(e)}")
        return False

def manual_cookie_instructions():
    """
    Provide instructions for manual cookie export
    """
    print("\n" + "="*60)
    print("MANUAL COOKIE EXPORT INSTRUCTIONS")
    print("="*60)
    print("\nIf automatic export failed, you can manually export cookies:")
    print("\n1. Install a browser extension:")
    print("   - Chrome: 'Get cookies.txt LOCALLY' extension")
    print("   - Firefox: 'cookies.txt' extension")
    
    print("\n2. Steps to export:")
    print("   a. Go to YouTube and make sure you're logged in")
    print("   b. Click the extension icon")
    print("   c. Export cookies for youtube.com")
    print("   d. Save the file as 'cookies.txt' in this directory")
    
    print("\n3. Alternative - Use browser developer tools:")
    print("   a. Go to YouTube (logged in)")
    print("   b. Press F12 to open developer tools")
    print("   c. Go to Application/Storage tab")
    print("   d. Click on Cookies -> https://www.youtube.com")
    print("   e. Copy all cookies and format them as Netscape format")
    
    print("\n4. Netscape cookie format example:")
    print("   # Netscape HTTP Cookie File")
    print("   .youtube.com	TRUE	/	FALSE	1234567890	cookie_name	cookie_value")
    
    print(f"\n5. Save the file as: {os.path.abspath('cookies.txt')}")
    print("\n" + "="*60)

def test_cookies(cookies_file='cookies.txt'):
    """
    Test if the cookies work with a simple yt-dlp command
    """
    if not os.path.exists(cookies_file):
        print(f"❌ Cookies file not found: {cookies_file}")
        return False
        
    print(f"Testing cookies with {cookies_file}...")
    
    try:
        # Test with a simple YouTube video
        cmd = [
            'yt-dlp',
            '--cookies', cookies_file,
            '--simulate',
            '--print', 'title',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ Cookies are working! Test download successful.")
            print(f"Video title: {result.stdout.strip()}")
            return True
        else:
            print(f"❌ Cookie test failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Cookie test timed out")
        return False
    except Exception as e:
        print(f"❌ Error testing cookies: {str(e)}")
        return False

def main():
    """
    Main function to handle cookie export
    """
    print("🍪 yt-dlp Cookie Export Utility")
    print("="*40)
    
    browsers = ['chrome', 'firefox', 'safari', 'edge']
    output_file = 'cookies.txt'
    
    # Try automatic export from different browsers
    success = False
    for browser in browsers:
        print(f"\nTrying {browser}...")
        if export_cookies_from_browser(browser, output_file):
            success = True
            break
    
    if success:
        # Test the exported cookies
        if test_cookies(output_file):
            print(f"\n✅ Setup complete! Cookies saved to {os.path.abspath(output_file)}")
            print("Your yt-dlp worker should now be able to download YouTube videos.")
        else:
            print("\n⚠️  Cookies exported but test failed. You may need to try manual export.")
            manual_cookie_instructions()
    else:
        print("\n❌ Automatic cookie export failed for all browsers.")
        manual_cookie_instructions()

if __name__ == "__main__":
    main()