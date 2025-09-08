# Video Title-Based Filename Implementation

## Overview

The yt-dlp worker has been enhanced to save files using the actual video title (slugified) instead of generic client_id-based filenames. This provides more meaningful and recognizable filenames for downloaded videos.

## Changes Made

### 1. Added Slugify Function

A new `slugify()` function was added to convert video titles into filesystem-safe filenames:

- Normalizes Unicode characters
- Removes or replaces problematic characters (`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`)
- Handles multiple spaces and dashes
- Truncates to reasonable length while preserving word boundaries
- Provides fallback for empty titles

### 2. Added Metadata Extraction

A new `extract_video_metadata()` method was added to the `DownloadWorker` class:

- Uses `yt-dlp --dump-json` to extract video metadata before download
- Extracts title, uploader, duration, and upload date
- Handles cookies for authentication
- Includes proper error handling and timeouts

### 3. Enhanced Upload Function

The `upload_to_gcs()` method was updated to accept video metadata:

- Generates filenames based on video title and uploader
- Format: `{title_slug}_by_{uploader_slug}_{timestamp}.{extension}`
- Falls back to original naming scheme if metadata is unavailable
- Maintains uniqueness with timestamp

### 4. Updated Process Flow

The `process_message()` function now:

1. Extracts video metadata first
2. Downloads the file using existing logic
3. Uploads with metadata-based filename
4. Provides better status messages with video title

## Filename Examples

### Before
```
abc123_20250907_143022_video.mp4
def456_20250907_143155_audio.m4a
```

### After
```
Rick-Astley-Never-Gonna-Give-You-Up-(Official-Video)-(4K-Remaster)_by_Rick-Astley_20250907_143022.mp4
How-to-Build-a-REST-API-with-Python-FastAPI_by_TechChannel_20250907_143155.mp4
```

## Benefits

1. **Meaningful Filenames**: Users can easily identify downloaded content
2. **Better Organization**: Files are self-describing
3. **Preserved Uniqueness**: Timestamp ensures no conflicts
4. **Fallback Safety**: Original naming scheme used if metadata extraction fails
5. **Cross-Platform Safe**: Slugified names work on all filesystems

## Technical Details

### Slugify Function Features
- Maximum length: 80 characters for title, 20 for uploader
- ASCII-only output for maximum compatibility
- Word boundary preservation when truncating
- Handles edge cases (empty strings, special characters)

### Metadata Extraction
- 30-second timeout to prevent hanging
- Uses existing cookie configuration
- Graceful degradation if extraction fails
- Logs extraction success/failure for debugging

### Upload Process
- Maintains existing GCS upload logic
- Preserves file extension from original download
- Adds timestamp for uniqueness
- Logs generated filename for tracking

## Error Handling

The implementation includes robust error handling:

- Metadata extraction failures don't break downloads
- Invalid characters are safely removed or replaced
- Empty titles default to "untitled"
- Original filename scheme used as fallback

## Testing

The implementation has been tested with:
- Various video platforms (YouTube, etc.)
- Special characters in titles
- Long titles requiring truncation
- Missing metadata scenarios
- Unicode characters and emojis

## Configuration

No additional configuration is required. The feature uses existing:
- Cookie files for authentication
- yt-dlp installation
- GCS upload settings
- Logging configuration

## Backward Compatibility

The changes are fully backward compatible:
- Existing downloads continue to work
- No changes to API or message format
- Fallback to original naming if needed
- No impact on other system components