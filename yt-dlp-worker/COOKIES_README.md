# Cookie Setup for yt-dlp Worker

This guide helps you set up cookies to bypass YouTube's bot detection.

## Quick Setup

1. **Run the cookie export script:**
   ```bash
   python export_cookies.py
   ```

2. **If automatic export works:**
   - The script will create `cookies.txt`
   - Test it automatically
   - You're ready to go!

3. **If automatic export fails:**
   - Follow the manual instructions provided by the script

## Manual Cookie Export

### Method 1: Browser Extension (Recommended)

1. **Install extension:**
   - Chrome: "Get cookies.txt LOCALLY"
   - Firefox: "cookies.txt"

2. **Export cookies:**
   - Go to YouTube (make sure you're logged in)
   - Click the extension icon
   - Export cookies for `youtube.com`
   - Save as `cookies.txt` in the worker directory

### Method 2: Browser Developer Tools

1. Go to YouTube (logged in)
2. Press F12 → Application/Storage → Cookies → https://www.youtube.com
3. Copy cookies and format as Netscape format:
   ```
   # Netscape HTTP Cookie File
   .youtube.com	TRUE	/	FALSE	1234567890	cookie_name	cookie_value
   ```

## Testing Cookies

Test your cookies with:
```bash
yt-dlp --cookies cookies.txt --simulate --print title "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## Security Notes

- Keep `cookies.txt` secure - it contains your login session
- Don't commit `cookies.txt` to version control
- Cookies expire - you may need to re-export periodically

## Troubleshooting

- **"Sign in to confirm you're not a bot"**: Your cookies are expired or invalid
- **"No such file"**: Make sure `cookies.txt` is in the worker directory
- **Still failing**: Try re-exporting cookies or using a different browser

## Environment Variables

The worker uses these environment variables:
- `COOKIES_FILE`: Path to cookies file (default: `cookies.txt`)

Update your `.env` file:
```
COOKIES_FILE=cookies.txt
```