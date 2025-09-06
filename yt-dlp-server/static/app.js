/**
 * DownloadManager - Handles form submission, URL validation, and UI updates
 */
class DownloadManager {
    constructor(clientId) {
        this.clientId = clientId;
        this.downloads = [];
        this.form = document.getElementById('download-form');
        this.urlInput = document.getElementById('url-input');
        this.submitBtn = document.getElementById('submit-btn');
        this.messagesArea = document.getElementById('messages');
        this.downloadsList = document.getElementById('downloads-list');
        this.connectionStatus = document.getElementById('connection-status');
        this.connectionText = document.getElementById('connection-text');
        
        // WebSocket properties
        this.websocket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Start with 1 second
        this.maxReconnectDelay = 30000; // Max 30 seconds
        
        this.initializeEventListeners();
        this.initializeNetworkMonitoring();
        this.connectWebSocket();
        
        // Set up periodic cleanup of old downloads
        setInterval(() => {
            this.cleanupOldDownloads();
            this.updateDownloadsList();
        }, 5 * 60 * 1000); // Clean up every 5 minutes
    }

    /**
     * Initialize form event listeners
     */
    initializeEventListeners() {
        this.form.addEventListener('submit', (e) => this.handleFormSubmit(e));
        this.urlInput.addEventListener('input', () => this.clearValidationErrors());
    }

    /**
     * Initialize network connectivity monitoring
     */
    initializeNetworkMonitoring() {
        // Monitor online/offline status
        window.addEventListener('online', () => {
            this.showSuccess('Internet connection restored.');
            
            // Attempt to reconnect WebSocket if disconnected
            if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
                setTimeout(() => {
                    this.manualReconnect();
                }, 1000);
            }
        });
        
        window.addEventListener('offline', () => {
            this.showError('Internet connection lost. Some features may not work until connection is restored.');
            this.updateConnectionStatus('disconnected', 'No internet connection');
        });
        
        // Check initial network status
        if (!navigator.onLine) {
            this.updateConnectionStatus('disconnected', 'No internet connection');
        }
    }

    /**
     * Handle form submission with validation
     */
    async handleFormSubmit(event) {
        event.preventDefault();
        
        const url = this.urlInput.value.trim();
        
        // Clear any previous validation errors
        this.clearValidationErrors();
        
        // Validate URL format
        if (!this.validateUrl(url)) {
            // Error message is shown by validateUrl method
            return;
        }

        // Check if URL is already being downloaded
        const existingDownload = this.downloads.find(d => d.url === url && ['pending', 'downloading'].includes(d.status));
        if (existingDownload) {
            this.showError('This URL is already being downloaded. Please wait for it to complete.');
            return;
        }

        // Disable form during submission
        this.setFormState(false);
        
        try {
            await this.submitDownload(url);
        } catch (error) {
            // Show user-friendly error message
            this.showError(error.message || 'Failed to submit download request. Please try again.');
            console.error('Download submission error:', error);
            
            // Add error styling to form
            this.urlInput.classList.add('error');
        } finally {
            // Re-enable form
            this.setFormState(true);
        }
    }

    /**
     * Validate URL format on client side
     */
    validateUrl(url) {
        if (!url) {
            this.showValidationError('Please enter a URL');
            return false;
        }

        // Remove whitespace
        url = url.trim();

        try {
            const urlObj = new URL(url);
            
            // Check for valid protocols
            if (!['http:', 'https:'].includes(urlObj.protocol)) {
                this.showValidationError('URL must start with http:// or https://');
                return false;
            }
            
            // Check for valid hostname
            if (!urlObj.hostname || urlObj.hostname.length < 3) {
                this.showValidationError('Please enter a valid website URL');
                return false;
            }
            
            // Basic check for suspicious URLs
            if (urlObj.hostname === 'localhost' || urlObj.hostname.startsWith('127.') || urlObj.hostname.startsWith('192.168.') || urlObj.hostname.startsWith('10.')) {
                this.showValidationError('Local URLs are not supported');
                return false;
            }
            
            return true;
        } catch (error) {
            this.showValidationError('Please enter a valid URL (e.g., https://www.youtube.com/watch?v=...)');
            return false;
        }
    }

    /**
     * Show validation error for form field
     */
    showValidationError(message) {
        // Add error class to input
        this.urlInput.classList.add('error');
        
        // Remove any existing validation message
        const existingError = this.form.querySelector('.validation-error');
        if (existingError) {
            existingError.remove();
        }
        
        // Create and show validation error message
        const errorDiv = document.createElement('div');
        errorDiv.className = 'validation-error';
        errorDiv.textContent = message;
        
        // Insert after the input field
        this.urlInput.parentNode.appendChild(errorDiv);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.remove();
            }
        }, 5000);
    }

    /**
     * Submit download request to server
     */
    async submitDownload(url) {
        try {
            // Add timeout to prevent hanging requests
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout
            
            const response = await fetch('/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: url,
                    client_id: this.clientId
                }),
                signal: controller.signal
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                let errorMessage;
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorData.message || `Server error: ${response.status} ${response.statusText}`;
                } catch (parseError) {
                    // If we can't parse the error response, use status text
                    errorMessage = `Network error: ${response.status} ${response.statusText}`;
                }
                
                // Provide user-friendly error messages based on status codes
                switch (response.status) {
                    case 400:
                        errorMessage = 'Invalid URL format. Please check the URL and try again.';
                        break;
                    case 429:
                        errorMessage = 'Too many requests. Please wait a moment before submitting another download.';
                        break;
                    case 500:
                        errorMessage = 'Server error occurred. Please try again in a few moments.';
                        break;
                    case 503:
                        errorMessage = 'Service temporarily unavailable. Please try again later.';
                        break;
                }
                
                throw new Error(errorMessage);
            }

            const result = await response.json();
            
            // Handle successful submission
            this.handleSubmissionSuccess(url, result);
            
            return result;
            
        } catch (error) {
            // Handle different types of errors with user-friendly messages
            if (error.name === 'AbortError') {
                throw new Error('Request timed out. Please check your connection and try again.');
            } else if (error.name === 'TypeError' && error.message.includes('fetch')) {
                throw new Error('Unable to connect to server. Please check your internet connection.');
            } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
                throw new Error('Network connection failed. Please check your internet connection and try again.');
            } else {
                // Re-throw the error with the original message if it's already user-friendly
                throw error;
            }
        }
    }

    /**
     * Handle successful form submission
     */
    handleSubmissionSuccess(url, result) {
        // Clear the form
        this.urlInput.value = '';
        
        // Add to downloads list if not already present
        const downloadId = result.id || this.generateDownloadId();
        const download = {
            id: downloadId,
            url: url,
            status: 'pending',
            progress: 0,
            message: 'Download request submitted - waiting for worker...',
            timestamp: new Date(),
            clientId: this.clientId  // Store client ID for matching
        };
        
        this.addDownload(download);
    }

    /**
     * Add download to the list and update UI
     */
    addDownload(download) {
        // Check if download already exists
        const existingIndex = this.downloads.findIndex(d => d.url === download.url);
        
        if (existingIndex >= 0) {
            // Update existing download
            this.downloads[existingIndex] = { ...this.downloads[existingIndex], ...download };
        } else {
            // Add new download
            this.downloads.push(download);
        }
        
        // Clean up old downloads before updating display
        this.cleanupOldDownloads();
        this.updateDownloadsList();
    }

    /**
     * Update the downloads list display
     */
    updateDownloadsList() {
        if (this.downloads.length === 0) {
            this.downloadsList.innerHTML = '<p class="no-downloads">No downloads yet. Submit a URL above to get started.</p>';
            return;
        }

        // Sort downloads by timestamp (newest first)
        const sortedDownloads = [...this.downloads].sort((a, b) => {
            const timeA = a.lastUpdate || a.timestamp;
            const timeB = b.lastUpdate || b.timestamp;
            return timeB - timeA;
        });

        const downloadsHtml = sortedDownloads.map(download => {
            const statusClass = `status-${download.status}`;
            const progressPercent = download.progress || 0;
            const showProgress = download.status === 'downloading' || progressPercent > 0;
            
            let messageHtml = download.message || 'Processing...';
            if (download.status === 'completed' && download.downloadUrl) {
                messageHtml = `<strong>Download completed!</strong><br><a href="${download.downloadUrl}" target="_blank" rel="noopener noreferrer" class="download-link">📥 ${download.fileName || 'Download File'}</a>`;
            }

            return `
                <div class="download-item ${statusClass}" data-id="${download.id}">
                    <div class="download-header">
                        <div class="download-url-container">
                            <span class="download-url" title="${download.url}">${this.truncateUrl(download.url)}</span>
                            <span class="download-timestamp">${this.formatTime(download.lastUpdate || download.timestamp)}</span>
                        </div>
                        <span class="status-badge ${statusClass}">${this.formatStatus(download.status)}</span>
                    </div>
                    
                    ${showProgress ? `
                        <div class="download-progress">
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${progressPercent}%"></div>
                            </div>
                            <div class="progress-text">${progressPercent.toFixed(1)}%</div>
                        </div>
                    ` : ''}
                    
                    <div class="download-details">
                        <div class="download-message">${messageHtml}</div>
                        ${this.renderDownloadMetadata(download)}
                    </div>
                </div>
            `;
        }).join('');

        this.downloadsList.innerHTML = downloadsHtml;
    }
    
    /**
     * Render additional download metadata (file size, speed, ETA)
     */
    renderDownloadMetadata(download) {
        const metadata = [];
        
        if (download.fileSize) {
            metadata.push(`<span class="metadata-item">Size: ${download.fileSize}</span>`);
        }
        
        if (download.downloadSpeed && download.status === 'downloading') {
            metadata.push(`<span class="metadata-item">Speed: ${download.downloadSpeed}</span>`);
        }
        
        if (download.eta && download.status === 'downloading') {
            metadata.push(`<span class="metadata-item">ETA: ${download.eta}</span>`);
        }
        
        return metadata.length > 0 ? `<div class="download-metadata">${metadata.join('')}</div>` : '';
    }
    
    /**
     * Format status for display
     */
    formatStatus(status) {
        const statusMap = {
            'pending': 'Pending',
            'downloading': 'Downloading',
            'completed': 'Completed',
            'error': 'Error',
            'failed': 'Failed',
            'cancelled': 'Cancelled'
        };
        
        return statusMap[status] || status.charAt(0).toUpperCase() + status.slice(1);
    }

    /**
     * Show error message to user
     */
    showError(message) {
        this.showMessage(message, 'error');
        
        // Add visual feedback to form
        this.urlInput.classList.add('error');
    }

    /**
     * Show success message to user
     */
    showSuccess(message) {
        this.showMessage(message, 'success');
    }

    /**
     * Show message in the messages area
     */
    showMessage(message, type = 'info') {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${type}`;
        messageDiv.textContent = message;
        
        // Add close button
        const closeBtn = document.createElement('button');
        closeBtn.className = 'message-close';
        closeBtn.innerHTML = '&times;';
        closeBtn.onclick = () => messageDiv.remove();
        messageDiv.appendChild(closeBtn);
        
        this.messagesArea.appendChild(messageDiv);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (messageDiv.parentNode) {
                messageDiv.remove();
            }
        }, 5000);
    }

    /**
     * Clear validation errors from form
     */
    clearValidationErrors() {
        this.urlInput.classList.remove('error');
        
        // Remove any validation error messages
        const existingError = this.form.querySelector('.validation-error');
        if (existingError) {
            existingError.remove();
        }
    }

    /**
     * Enable/disable form elements
     */
    setFormState(enabled) {
        this.urlInput.disabled = !enabled;
        this.submitBtn.disabled = !enabled;
        
        if (enabled) {
            this.submitBtn.textContent = 'Download';
        } else {
            this.submitBtn.textContent = 'Submitting...';
        }
    }

    /**
     * Generate a unique download ID
     */
    generateDownloadId() {
        return 'download_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
    }

    /**
     * Truncate URL for display
     */
    truncateUrl(url, maxLength = 50) {
        if (url.length <= maxLength) {
            return url;
        }
        return url.substring(0, maxLength - 3) + '...';
    }

    /**
     * Format timestamp for display
     */
    formatTime(timestamp) {
        const now = new Date();
        const diff = now - timestamp;
        
        // If less than 1 minute ago, show "just now"
        if (diff < 60000) {
            return 'just now';
        }
        
        // If less than 1 hour ago, show minutes
        if (diff < 3600000) {
            const minutes = Math.floor(diff / 60000);
            return `${minutes}m ago`;
        }
        
        // If today, show time
        if (timestamp.toDateString() === now.toDateString()) {
            return timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        
        // Otherwise show date and time
        return timestamp.toLocaleString([], { 
            month: 'short', 
            day: 'numeric', 
            hour: '2-digit', 
            minute: '2-digit' 
        });
    }
    
    /**
     * Clean up old completed downloads to prevent list from growing too large
     */
    cleanupOldDownloads() {
        const maxDownloads = 50;
        const maxAge = 24 * 60 * 60 * 1000; // 24 hours
        const now = new Date();
        
        // Remove downloads older than maxAge or keep only the most recent maxDownloads
        this.downloads = this.downloads.filter((download, index) => {
            const age = now - (download.lastUpdate || download.timestamp);
            const isRecent = age < maxAge;
            const isInLimit = index < maxDownloads;
            
            // Keep if it's recent or within limit, and not completed/error for too long
            if (download.status === 'completed' || download.status === 'error') {
                return isRecent && isInLimit;
            }
            
            // Always keep active downloads
            return true;
        });
        
        // Sort by most recent activity
        this.downloads.sort((a, b) => {
            const timeA = a.lastUpdate || a.timestamp;
            const timeB = b.lastUpdate || b.timestamp;
            return timeB - timeA;
        });
    }

    /**
     * Initialize WebSocket connection
     */
    connectWebSocket() {
        // Check network connectivity first
        if (!navigator.onLine) {
            this.updateConnectionStatus('disconnected', 'No internet connection');
            return;
        }
        
        // Update connection status to connecting
        this.updateConnectionStatus('connecting', 'Connecting to server...');
        
        try {
            // Determine WebSocket URL based on current location
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/${this.clientId}`;
            
            console.log('Connecting to WebSocket:', wsUrl);
            
            // Close existing connection if any
            if (this.websocket) {
                this.websocket.close();
            }
            
            this.websocket = new WebSocket(wsUrl);
            
            // Set connection timeout
            const connectionTimeout = setTimeout(() => {
                if (this.websocket && this.websocket.readyState === WebSocket.CONNECTING) {
                    console.log('WebSocket connection timeout');
                    this.websocket.close();
                    this.updateConnectionStatus('disconnected', 'Connection timeout');
                    this.scheduleReconnect();
                }
            }, 10000); // 10 second timeout
            
            // Set up event handlers
            this.websocket.onopen = (event) => {
                clearTimeout(connectionTimeout);
                this.handleWebSocketOpen(event);
            };
            this.websocket.onmessage = (event) => this.handleWebSocketMessage(event);
            this.websocket.onclose = (event) => {
                clearTimeout(connectionTimeout);
                this.handleWebSocketClose(event);
            };
            this.websocket.onerror = (event) => {
                clearTimeout(connectionTimeout);
                this.handleWebSocketError(event);
            };
            
        } catch (error) {
            console.error('Failed to create WebSocket connection:', error);
            this.updateConnectionStatus('disconnected', 'Connection failed');
            
            // Provide user-friendly error message
            let errorMessage = 'Failed to connect to server.';
            if (error.name === 'SecurityError') {
                errorMessage = 'Connection blocked by security policy. Please check your browser settings.';
            } else if (error.message.includes('network')) {
                errorMessage = 'Network error. Please check your internet connection.';
            }
            
            this.showError(errorMessage);
            this.scheduleReconnect();
        }
    }

    /**
     * Handle WebSocket connection opened
     */
    handleWebSocketOpen(event) {
        console.log('WebSocket connected successfully');
        this.updateConnectionStatus('connected', 'Connected to server');
        
        // Reset reconnection attempts on successful connection
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        
        // Remove manual reconnect message if present
        if (this.reconnectMessage && this.reconnectMessage.parentNode) {
            this.reconnectMessage.remove();
            this.reconnectMessage = null;
        }
        
        // Connection status is already shown in the status indicator, no need for popup messages
        this.hasBeenDisconnected = false;
    }

    /**
     * Handle incoming WebSocket messages
     */
    handleWebSocketMessage(event) {
        try {
            const data = JSON.parse(event.data);
            console.log('WebSocket message received:', data);
            
            // Handle different message types
            switch (data.type) {
                case 'ping':
                    this.websocket.send(JSON.stringify({ type: 'pong' }));
                    break;
                case 'status':
                case 'download_status':
                case 'progress':
                    this.handleStatusUpdate(data);
                    break;
                case 'connection':
                    console.log('Connection message:', data.message);
                    // Connection status is already shown in the status indicator
                    break;
                case 'error':
                    this.showError(`Server error: ${data.message || 'Unknown server error occurred'}`);
                    break;
                case 'info':
                    if (data.message) {
                        this.showMessage(data.message, 'info');
                    }
                    break;
                case 'warning':
                    if (data.message) {
                        this.showMessage(data.message, 'warning');
                    }
                    break;
                default:
                    // Handle messages without explicit type as status updates
                    if (data.message || data.url || data.progress !== undefined) {
                        this.handleStatusUpdate(data);
                    } else {
                        console.log('Unknown message type:', data.type, data);
                        // Don't show unknown messages to users to avoid confusion
                    }
            }
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error, 'Raw data:', event.data);
            
            // Try to handle as plain text message, but be more careful
            if (typeof event.data === 'string' && event.data.trim()) {
                const message = event.data.trim();
                // Only show if it looks like a meaningful message
                if (message.length > 0 && message.length < 500) {
                    this.showMessage(`Server: ${message}`, 'info');
                }
            } else {
                // Log parsing errors but don't show to user unless in debug mode
                console.warn('Received unparseable WebSocket message');
            }
        }
    }

    /**
     * Handle WebSocket connection closed
     */
    handleWebSocketClose(event) {
        console.log('WebSocket connection closed:', event.code, event.reason);
        
        // Mark that we've been disconnected for reconnection messaging
        this.hasBeenDisconnected = true;
        
        if (event.wasClean) {
            this.updateConnectionStatus('disconnected', 'Connection closed');
        } else {
            this.updateConnectionStatus('disconnected', 'Connection lost');
            
            // Provide user-friendly error messages based on close codes
            let errorMessage = 'Connection lost. Attempting to reconnect...';
            switch (event.code) {
                case 1006:
                    errorMessage = 'Connection lost unexpectedly. Attempting to reconnect...';
                    break;
                case 1011:
                    errorMessage = 'Server error caused disconnection. Attempting to reconnect...';
                    break;
                case 1012:
                    errorMessage = 'Server is restarting. Attempting to reconnect...';
                    break;
            }
            
            if (this.reconnectAttempts === 0) {
                this.showMessage(errorMessage, 'warning');
            }
            
            this.scheduleReconnect();
        }
    }

    /**
     * Handle WebSocket errors
     */
    handleWebSocketError(event) {
        console.error('WebSocket error:', event);
        this.updateConnectionStatus('disconnected', 'Connection error');
        
        // Show user-friendly error message
        if (this.reconnectAttempts === 0) {
            this.showError('Lost connection to server. Attempting to reconnect...');
        }
    }

    /**
     * Handle status updates from WebSocket
     */
    handleStatusUpdate(data) {
        console.log('Status update received:', data);
        
        // Extract relevant information from the status update
        const { message, client_id, progress, url, status, download_id, file_name, download_url } = data;
        
        // Only process updates for our client
        if (client_id && client_id !== this.clientId) {
            return;
        }
        
        // Find or create download entry
        let download = null;
        let downloadIndex = -1;
        
        // Try to find existing download by ID first, then by URL, then by client_id for pending downloads
        if (download_id) {
            downloadIndex = this.downloads.findIndex(d => d.id === download_id);
        }
        
        if (downloadIndex === -1 && url) {
            downloadIndex = this.downloads.findIndex(d => d.url === url);
        }
        
        // If no specific download found, try to find the most recent pending download for this client
        if (downloadIndex === -1 && !url) {
            downloadIndex = this.downloads.findIndex(d => 
                ['pending', 'downloading', 'processing'].includes(d.status) && 
                (new Date() - d.timestamp) < 300000 // Within last 5 minutes
            );
        }
        
        if (downloadIndex >= 0) {
            // Update existing download
            download = this.downloads[downloadIndex];
        } else if (url) {
            // Create new download entry if we have a URL
            download = {
                id: download_id || this.generateDownloadId(),
                url: url,
                status: 'pending',
                progress: 0,
                message: 'Download initiated',
                timestamp: new Date()
            };
            this.downloads.push(download);
            downloadIndex = this.downloads.length - 1;
        } else {
            // If we can't find or create a download entry, just show the message
            if (message) {
                this.showMessage(`Server: ${message}`, 'info');
            }
            return;
        }
        
        if (download) {
            // Update download properties based on received data
            if (status) {
                download.status = status.toLowerCase();
            }
            
            if (typeof progress === 'number') {
                download.progress = Math.max(0, Math.min(100, progress));
            }
            
            if (message) {
                download.message = message;
            }

            if (file_name) {
                download.fileName = file_name;
            }

            if (download_url) {
                download.downloadUrl = download_url;
            }
            
            // Update additional progress data
            if (data.download_speed) {
                download.downloadSpeed = data.download_speed;
            }
            
            if (data.eta) {
                download.eta = data.eta;
            }
            
            if (data.file_size) {
                download.fileSize = data.file_size;
            }
            
            // Update timestamp for latest activity
            download.lastUpdate = new Date();
            
            // Parse additional information from message if available
            this.parseStatusMessage(download, message);
            
            // Update the downloads list display
            this.updateDownloadsList();
            
            // Show notification for significant status changes
            this.showStatusNotification(download, message);
        } else {
            // If we can't associate with a specific download, show general message
            if (message) {
                this.showMessage(`Server: ${message}`, 'info');
            }
        }
    }
    
    /**
     * Parse additional information from status messages
     */
    parseStatusMessage(download, message) {
        if (!message) return;
        
        const lowerMessage = message.toLowerCase();
        
        // Extract progress percentage from message if present
        const progressMatch = message.match(/(\d+(?:\.\d+)?)%/);
        if (progressMatch) {
            const progressValue = parseFloat(progressMatch[1]);
            download.progress = Math.max(0, Math.min(100, progressValue));
        }
        
        // Extract file size information
        const sizeMatch = message.match(/(\d+(?:\.\d+)?)\s*(MB|GB|KB|bytes?)/i);
        if (sizeMatch) {
            download.fileSize = `${sizeMatch[1]} ${sizeMatch[2]}`;
        }
        
        // Extract download speed information
        const speedMatch = message.match(/(\d+(?:\.\d+)?)\s*(MB\/s|KB\/s|B\/s)/i);
        if (speedMatch) {
            download.downloadSpeed = `${speedMatch[1]} ${speedMatch[2]}`;
        }
        
        // Extract ETA information
        const etaMatch = message.match(/ETA\s+(\d+:\d+(?::\d+)?)/i);
        if (etaMatch) {
            download.eta = etaMatch[1];
        }
        
        // Determine status from message content if not explicitly provided
        if (!download.status || download.status === 'pending') {
            if (lowerMessage.includes('downloading') || lowerMessage.includes('progress')) {
                download.status = 'downloading';
            } else if (lowerMessage.includes('completed') || lowerMessage.includes('finished')) {
                download.status = 'completed';
                download.progress = 100;
            } else if (lowerMessage.includes('error') || lowerMessage.includes('failed')) {
                download.status = 'error';
            } else if (lowerMessage.includes('starting') || lowerMessage.includes('initiated')) {
                download.status = 'downloading';
            }
        }
    }
    
    /**
     * Show notifications for significant status changes
     */
    showStatusNotification(download, message) {
        // Popup notifications removed - status updates are now only shown in the download status list
        // This keeps the UI cleaner and less intrusive while still providing all status information
    }

    /**
     * Update connection status indicator
     */
    updateConnectionStatus(status, message) {
        // Remove existing status classes
        this.connectionStatus.classList.remove('connected', 'connecting', 'disconnected');
        
        // Add new status class
        this.connectionStatus.classList.add(status);
        
        // Update status text
        this.connectionText.textContent = message;
        
        console.log(`Connection status updated: ${status} - ${message}`);
    }

    /**
     * Schedule WebSocket reconnection with exponential backoff
     */
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('Max reconnection attempts reached');
            this.updateConnectionStatus('disconnected', 'Connection failed - please refresh page');
            this.showError('Unable to connect to server after multiple attempts. Please check your internet connection and refresh the page.');
            
            // Offer manual reconnection option
            this.showReconnectOption();
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay);
        
        console.log(`Scheduling reconnection attempt ${this.reconnectAttempts} in ${delay}ms`);
        
        // Show countdown in status
        let remainingSeconds = Math.ceil(delay / 1000);
        this.updateConnectionStatus('connecting', `Reconnecting in ${remainingSeconds}s... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        
        // Update countdown every second
        const countdownInterval = setInterval(() => {
            remainingSeconds--;
            if (remainingSeconds > 0) {
                this.updateConnectionStatus('connecting', `Reconnecting in ${remainingSeconds}s... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            } else {
                clearInterval(countdownInterval);
                this.updateConnectionStatus('connecting', `Attempting to reconnect... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            }
        }, 1000);
        
        setTimeout(() => {
            clearInterval(countdownInterval);
            
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                // Already connected, no need to reconnect
                return;
            }
            
            this.connectWebSocket();
        }, delay);
    }

    /**
     * Show manual reconnection option when auto-reconnect fails
     */
    showReconnectOption() {
        const reconnectDiv = document.createElement('div');
        reconnectDiv.className = 'message message-warning';
        reconnectDiv.innerHTML = `
            Connection lost. Real-time updates are disabled.
            <button class="reconnect-btn" onclick="window.downloadManager.manualReconnect()">Try Again</button>
        `;
        
        this.messagesArea.appendChild(reconnectDiv);
        
        // Store reference for removal on successful reconnection
        this.reconnectMessage = reconnectDiv;
    }

    /**
     * Manual reconnection triggered by user
     */
    manualReconnect() {
        // Reset reconnection attempts
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        
        // Remove manual reconnect message
        if (this.reconnectMessage && this.reconnectMessage.parentNode) {
            this.reconnectMessage.remove();
            this.reconnectMessage = null;
        }
        
        // Close existing connection if any
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
        
        // Check network connectivity before attempting reconnection
        this.checkNetworkConnectivity().then(isOnline => {
            if (!isOnline) {
                this.showError('No internet connection detected. Please check your network connection.');
                return;
            }
            
            // Attempt to reconnect
            this.connectWebSocket();
        });
    }

    /**
     * Check network connectivity
     */
    async checkNetworkConnectivity() {
        if (!navigator.onLine) {
            return false;
        }
        
        try {
            // Try to fetch a small resource from the same origin
            const response = await fetch('/static/style.css', {
                method: 'HEAD',
                cache: 'no-cache'
            });
            return response.ok;
        } catch (error) {
            console.log('Network connectivity check failed:', error);
            return false;
        }
    }

    /**
     * Close WebSocket connection
     */
    disconnectWebSocket() {
        if (this.websocket) {
            console.log('Closing WebSocket connection');
            this.websocket.close(1000, 'Client disconnecting');
            this.websocket = null;
        }
    }
}

// Initialize the download manager when the page loads
document.addEventListener('DOMContentLoaded', () => {
    if (typeof window.CLIENT_ID !== 'undefined') {
        window.downloadManager = new DownloadManager(window.CLIENT_ID);
    } else {
        console.error('CLIENT_ID not found. Make sure the server is providing the client ID.');
    }
});

// Clean up WebSocket connection when page is unloaded
window.addEventListener('beforeunload', () => {
    if (window.downloadManager && window.downloadManager.websocket) {
        window.downloadManager.disconnectWebSocket();
    }
});teDownloadsList();
            
            // Show notification for significant status changes
            this.showStatusNotification(download, message);
        } else {
            // If we can't associate with a specific download, show general message
            if (message) {
                this.showMessage(`Server: ${message}`, 'info');
            }
        }
    }
    
    /**
     * Parse additional information from status messages
     */
    parseStatusMessage(download, message) {
        if (!message) return;
        
        const lowerMessage = message.toLowerCase();
        
        // Extract progress percentage from message if present
        const progressMatch = message.match(/(\d+(?:\.\d+)?)%/);
        if (progressMatch) {
            const progressValue = parseFloat(progressMatch[1]);
            download.progress = Math.max(0, Math.min(100, progressValue));
        }
        
        // Extract file size information
        const sizeMatch = message.match(/(\d+(?:\.\d+)?)\s*(MB|GB|KB|bytes?)/i);
        if (sizeMatch) {
            download.fileSize = `${sizeMatch[1]} ${sizeMatch[2]}`;
        }
        
        // Extract download speed information
        const speedMatch = message.match(/(\d+(?:\.\d+)?)\s*(MB\/s|KB\/s|B\/s)/i);
        if (speedMatch) {
            download.downloadSpeed = `${speedMatch[1]} ${speedMatch[2]}`;
        }
        
        // Extract ETA information
        const etaMatch = message.match(/ETA\s+(\d+:\d+(?::\d+)?)/i);
        if (etaMatch) {
            download.eta = etaMatch[1];
        }
        
        // Determine status from message content if not explicitly provided
        if (!download.status || download.status === 'pending') {
            if (lowerMessage.includes('downloading') || lowerMessage.includes('progress')) {
                download.status = 'downloading';
            } else if (lowerMessage.includes('completed') || lowerMessage.includes('finished')) {
                download.status = 'completed';
                download.progress = 100;
            } else if (lowerMessage.includes('error') || lowerMessage.includes('failed')) {
                download.status = 'error';
            } else if (lowerMessage.includes('starting') || lowerMessage.includes('initiated')) {
                download.status = 'downloading';
            }
        }
    }
    
    /**
     * Show notifications for significant status changes
     */
    showStatusNotification(download, message) {
        // Popup notifications removed - status updates are now only shown in the download status list
        // This keeps the UI cleaner and less intrusive while still providing all status information
    }

    /**
     * Update connection status indicator
     */
    updateConnectionStatus(status, message) {
        // Remove existing status classes
        this.connectionStatus.classList.remove('connected', 'connecting', 'disconnected');
        
        // Add new status class
        this.connectionStatus.classList.add(status);
        
        // Update status text
        this.connectionText.textContent = message;
        
        console.log(`Connection status updated: ${status} - ${message}`);
    }

    /**
     * Schedule WebSocket reconnection with exponential backoff
     */
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('Max reconnection attempts reached');
            this.updateConnectionStatus('disconnected', 'Connection failed - please refresh page');
            this.showError('Unable to connect to server after multiple attempts. Please check your internet connection and refresh the page.');
            
            // Offer manual reconnection option
            this.showReconnectOption();
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay);
        
        console.log(`Scheduling reconnection attempt ${this.reconnectAttempts} in ${delay}ms`);
        
        // Show countdown in status
        let remainingSeconds = Math.ceil(delay / 1000);
        this.updateConnectionStatus('connecting', `Reconnecting in ${remainingSeconds}s... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        
        // Update countdown every second
        const countdownInterval = setInterval(() => {
            remainingSeconds--;
            if (remainingSeconds > 0) {
                this.updateConnectionStatus('connecting', `Reconnecting in ${remainingSeconds}s... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            } else {
                clearInterval(countdownInterval);
                this.updateConnectionStatus('connecting', `Attempting to reconnect... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            }
        }, 1000);
        
        setTimeout(() => {
            clearInterval(countdownInterval);
            
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                // Already connected, no need to reconnect
                return;
            }
            
            this.connectWebSocket();
        }, delay);
    }

    /**
     * Show manual reconnection option when auto-reconnect fails
     */
    showReconnectOption() {
        const reconnectDiv = document.createElement('div');
        reconnectDiv.className = 'message message-warning';
        reconnectDiv.innerHTML = `
            Connection lost. Real-time updates are disabled.
            <button class="reconnect-btn" onclick="window.downloadManager.manualReconnect()">Try Again</button>
        `;
        
        this.messagesArea.appendChild(reconnectDiv);
        
        // Store reference for removal on successful reconnection
        this.reconnectMessage = reconnectDiv;
    }

    /**
     * Manual reconnection triggered by user
     */
    manualReconnect() {
        // Reset reconnection attempts
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        
        // Remove manual reconnect message
        if (this.reconnectMessage && this.reconnectMessage.parentNode) {
            this.reconnectMessage.remove();
            this.reconnectMessage = null;
        }
        
        // Close existing connection if any
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
        
        // Check network connectivity before attempting reconnection
        this.checkNetworkConnectivity().then(isOnline => {
            if (!isOnline) {
                this.showError('No internet connection detected. Please check your network connection.');
                return;
            }
            
            // Attempt to reconnect
            this.connectWebSocket();
        });
    }

    /**
     * Check network connectivity
     */
    async checkNetworkConnectivity() {
        if (!navigator.onLine) {
            return false;
        }
        
        try {
            // Try to fetch a small resource from the same origin
            const response = await fetch('/static/style.css', {
                method: 'HEAD',
                cache: 'no-cache'
            });
            return response.ok;
        } catch (error) {
            console.log('Network connectivity check failed:', error);
            return false;
        }
    }

    /**
     * Close WebSocket connection
     */
    disconnectWebSocket() {
        if (this.websocket) {
            console.log('Closing WebSocket connection');
            this.websocket.close(1000, 'Client disconnecting');
            this.websocket = null;
        }
    }
}

// Initialize the download manager when the page loads
document.addEventListener('DOMContentLoaded', () => {
    if (typeof window.CLIENT_ID !== 'undefined') {
        window.downloadManager = new DownloadManager(window.CLIENT_ID);
    } else {
        console.error('CLIENT_ID not found. Make sure the server is providing the client ID.');
    }
});

// Clean up WebSocket connection when page is unloaded
window.addEventListener('beforeunload', () => {
    if (window.downloadManager && window.downloadManager.websocket) {
        window.downloadManager.disconnectWebSocket();
    }
});