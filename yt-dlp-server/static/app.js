
      // Embedded JavaScript with Matrix/Hacker aesthetic enhancements
      class DownloadManager {
        constructor(clientId) {
          this.clientId = clientId;
          this.downloads = [];
          this.form = document.getElementById("download-form");
          this.urlInput = document.getElementById("url-input");
          this.submitBtn = document.getElementById("submit-btn");
          this.messagesArea = document.getElementById("messages");
          this.downloadsList = document.getElementById("downloads-list");
          this.connectionStatus = document.getElementById("connection-status");
          this.connectionText = document.getElementById("connection-text");

          // WebSocket properties
          this.websocket = null;
          this.reconnectAttempts = 0;
          this.maxReconnectAttempts = 5;
          this.reconnectDelay = 1000;
          this.maxReconnectDelay = 30000;

          // Enhanced progress properties
          this.smoothProgress = {};
          this.progressAnimations = {};

          this.initializeEventListeners();
          this.initializeNetworkMonitoring();
          this.connectWebSocket();

          // Cleanup old downloads every 5 minutes
          setInterval(() => {
            this.cleanupOldDownloads();
            this.updateDownloadsList();
          }, 5 * 60 * 1000);
        }

        initializeEventListeners() {
          this.form.addEventListener("submit", (e) => this.handleFormSubmit(e));
          this.urlInput.addEventListener("input", () =>
            this.clearValidationErrors()
          );
        }

        initializeNetworkMonitoring() {
          window.addEventListener("online", () => {
            this.showSuccess("Network connection restored");
            if (
              !this.websocket ||
              this.websocket.readyState !== WebSocket.OPEN
            ) {
              setTimeout(() => this.manualReconnect(), 1000);
            }
          });

          window.addEventListener("offline", () => {
            this.showError("Network connection lost");
            this.updateConnectionStatus(
              "disconnected",
              "No Network Connection"
            );
          });

          if (!navigator.onLine) {
            this.updateConnectionStatus(
              "disconnected",
              "No Network Connection"
            );
          }
        }

        async handleFormSubmit(event) {
          event.preventDefault();

          const url = this.urlInput.value.trim();

          this.clearValidationErrors();

          if (!this.validateUrl(url)) {
            return;
          }

          const existingDownload = this.downloads.find(
            (d) =>
              d.url === url && ["pending", "downloading"].includes(d.status)
          );
          if (existingDownload) {
            this.showError("Target already in queue. Standby for completion.");
            return;
          }

          this.setFormState(false);

          try {
            await this.submitDownload(url);
          } catch (error) {
            this.showError(error.message || "Request failed. Retry operation.");
            console.error("Download submission error:", error);
            this.urlInput.classList.add("error");
          } finally {
            this.setFormState(true);
          }
        }

        validateUrl(url) {
          if (!url) {
            this.showValidationError("URL required for operation");
            return false;
          }

          url = url.trim();

          try {
            const urlObj = new URL(url);

            if (!["http:", "https:"].includes(urlObj.protocol)) {
              this.showValidationError("Protocol must be HTTP or HTTPS");
              return false;
            }

            if (!urlObj.hostname || urlObj.hostname.length < 3) {
              this.showValidationError("Invalid hostname detected");
              return false;
            }

            if (
              urlObj.hostname === "localhost" ||
              urlObj.hostname.startsWith("127.") ||
              urlObj.hostname.startsWith("192.168.") ||
              urlObj.hostname.startsWith("10.")
            ) {
              this.showValidationError("Local addresses not permitted");
              return false;
            }

            return true;
          } catch (error) {
            this.showValidationError("Malformed URL detected");
            return false;
          }
        }

        showValidationError(message) {
          this.urlInput.classList.add("error");

          const existingError = this.form.querySelector(".validation-error");
          if (existingError) {
            existingError.remove();
          }

          const errorDiv = document.createElement("div");
          errorDiv.className = "validation-error";
          errorDiv.textContent = message;

          this.urlInput.parentNode.appendChild(errorDiv);

          setTimeout(() => {
            if (errorDiv.parentNode) {
              errorDiv.remove();
            }
          }, 5000);
        }

        async submitDownload(url) {
          try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000);

            const response = await fetch("/submit", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                url: url,
                client_id: this.clientId,
              }),
              signal: controller.signal,
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
              let errorMessage;
              try {
                const errorData = await response.json();
                errorMessage =
                  errorData.detail ||
                  errorData.message ||
                  `Server error: ${response.status}`;
              } catch (parseError) {
                errorMessage = `Network error: ${response.status}`;
              }

              switch (response.status) {
                case 400:
                  errorMessage = "Invalid URL format detected";
                  break;
                case 429:
                  errorMessage = "Rate limit exceeded. Standby.";
                  break;
                case 500:
                  errorMessage = "Server malfunction. Retry operation.";
                  break;
                case 503:
                  errorMessage = "Service unavailable. Retry later.";
                  break;
              }

              throw new Error(errorMessage);
            }

            const result = await response.json();
            this.handleSubmissionSuccess(url, result);
            return result;
          } catch (error) {
            if (error.name === "AbortError") {
              throw new Error("Request timeout. Check connection.");
            } else if (
              error.name === "TypeError" &&
              error.message.includes("fetch")
            ) {
              throw new Error("Connection failed. Check network.");
            } else if (
              error.message.includes("NetworkError") ||
              error.message.includes("Failed to fetch")
            ) {
              throw new Error("Network failure detected.");
            } else {
              throw error;
            }
          }
        }

        handleSubmissionSuccess(url, result) {
          this.urlInput.value = "";

          const downloadId = result.id || this.generateDownloadId();
          const download = {
            id: downloadId,
            url: url,
            status: "pending",
            progress: 0,
            message: "Request queued - awaiting worker response",
            timestamp: new Date(),
            clientId: this.clientId,
            fakeProgressActive: false,
          };

          this.addDownload(download);

          // Start fake progress after a short delay
          setTimeout(() => {
            this.startFakeProgress(downloadId);
          }, 2000);
        }

        startFakeProgress(downloadId) {
          const download = this.downloads.find((d) => d.id === downloadId);
          if (
            !download ||
            download.status !== "pending" ||
            download.fakeProgressActive
          ) {
            return;
          }

          download.fakeProgressActive = true;
          download.status = "downloading";
          download.message = "Analyzing video and preparing download...";
          download.progressType = "simulated";

          // Initialize enhanced progress data
          download.downloadSpeed = null;
          download.eta = null;
          download.fileSize = null;

          let fakeProgress = 0;
          const progressStages = [
            {
              progress: 15,
              message: "Fetching video information...",
              duration: 3000,
              speed: "Initializing...",
              eta: "Calculating...",
            },
            {
              progress: 35,
              message: "Selecting best quality format...",
              duration: 4000,
              speed: "Analyzing...",
              eta: "Estimating...",
            },
            {
              progress: 55,
              message: "Initializing download stream...",
              duration: 3000,
              speed: () => this.generateFakeSpeed(0.8),
              eta: () => this.calculateFakeETA(55),
              fileSize: () => this.generateFakeFileSize(),
            },
            {
              progress: 75,
              message: "Downloading video content...",
              duration: 5000,
              speed: () => this.generateFakeSpeed(1.0),
              eta: () => this.calculateFakeETA(75),
            },
            {
              progress: 90,
              message: "Processing and finalizing...",
              duration: 2000,
              speed: () => this.generateFakeSpeed(0.6),
              eta: () => this.calculateFakeETA(90),
            },
          ];

          let stageIndex = 0;

          const updateFakeProgress = () => {
            if (
              !download.fakeProgressActive ||
              download.status === "completed" ||
              download.status === "error"
            ) {
              return;
            }

            if (stageIndex < progressStages.length) {
              const stage = progressStages[stageIndex];
              const startProgress = fakeProgress;
              const targetProgress = stage.progress;
              const duration = stage.duration;
              const steps = 20;
              const stepDuration = duration / steps;
              const progressIncrement =
                (targetProgress - startProgress) / steps;

              download.message = stage.message;

              // Update enhanced metadata
              if (typeof stage.speed === "function") {
                download.downloadSpeed = stage.speed();
              } else if (stage.speed) {
                download.downloadSpeed = stage.speed;
              }

              if (typeof stage.eta === "function") {
                download.eta = stage.eta();
              } else if (stage.eta) {
                download.eta = stage.eta;
              }

              if (typeof stage.fileSize === "function") {
                download.fileSize = stage.fileSize();
              } else if (stage.fileSize) {
                download.fileSize = stage.fileSize;
              }

              let step = 0;
              const progressInterval = setInterval(() => {
                if (
                  !download.fakeProgressActive ||
                  download.status === "completed" ||
                  download.status === "error"
                ) {
                  clearInterval(progressInterval);
                  return;
                }

                step++;
                fakeProgress = Math.min(
                  targetProgress,
                  startProgress + progressIncrement * step
                );
                download.progress = fakeProgress;

                // Update dynamic metadata during progress
                if (stageIndex >= 2) {
                  // After initialization stages
                  if (Math.random() < 0.4) {
                    // Update speed occasionally
                    download.downloadSpeed = this.generateFakeSpeed();
                  }
                  download.eta = this.calculateFakeETA(fakeProgress);
                }

                // Add some randomness to make it look realistic
                if (Math.random() < 0.3) {
                  download.progress += Math.random() * 2 - 1;
                  download.progress = Math.max(
                    0,
                    Math.min(100, download.progress)
                  );
                }

                this.updateDownloadsList();

                if (step >= steps) {
                  clearInterval(progressInterval);
                  stageIndex++;

                  setTimeout(() => {
                    if (download.fakeProgressActive) {
                      updateFakeProgress();
                    }
                  }, 500);
                }
              }, stepDuration);
            } else {
              // Final stage - slow progress to 95% and wait
              download.message = "Finalizing download...";
              download.downloadSpeed = this.generateFakeSpeed(0.3);
              download.eta = "< 1min";

              const finalInterval = setInterval(() => {
                if (
                  !download.fakeProgressActive ||
                  download.status === "completed" ||
                  download.status === "error"
                ) {
                  clearInterval(finalInterval);
                  return;
                }

                if (download.progress < 95) {
                  download.progress += 0.2 + Math.random() * 0.3;
                  download.progress = Math.min(95, download.progress);
                  download.eta = this.calculateFakeETA(download.progress);
                  this.updateDownloadsList();
                }
              }, 1000);

              setTimeout(() => {
                if (
                  download.fakeProgressActive &&
                  download.status === "downloading"
                ) {
                  clearInterval(finalInterval);
                  download.message = "Download taking longer than expected...";
                  download.downloadSpeed = "Variable";
                  download.eta = "Unknown";
                  this.updateDownloadsList();
                }
              }, 30000);
            }
          };

          updateFakeProgress();
        }

        generateFakeSpeed(multiplier = 1) {
          const baseSpeed = 0.5 + Math.random() * 3; // 0.5 - 3.5 MB/s
          const adjustedSpeed = baseSpeed * multiplier;

          if (adjustedSpeed < 1) {
            return `${(adjustedSpeed * 1024).toFixed(0)}KB/s`;
          } else {
            return `${adjustedSpeed.toFixed(1)}MB/s`;
          }
        }

        calculateFakeETA(currentProgress) {
          if (currentProgress < 5) return "Calculating...";
          if (currentProgress > 90) return "< 1min";

          const remainingProgress = 100 - currentProgress;
          const estimatedMinutes = Math.ceil(
            (remainingProgress / 100) * (5 + Math.random() * 10)
          );

          if (estimatedMinutes < 1) return "< 1min";
          if (estimatedMinutes < 60) return `${estimatedMinutes}min`;

          const hours = Math.floor(estimatedMinutes / 60);
          const mins = estimatedMinutes % 60;
          return `${hours}h ${mins}min`;
        }

        generateFakeFileSize() {
          const sizes = [
            "25.3MB",
            "47.8MB",
            "89.2MB",
            "156.7MB",
            "234.1MB",
            "312.5MB",
          ];
          return sizes[Math.floor(Math.random() * sizes.length)];
        }

        stopFakeProgress(download) {
          if (download.fakeProgressActive) {
            download.fakeProgressActive = false;
          }
        }

        addDownload(download) {
          const existingIndex = this.downloads.findIndex(
            (d) => d.url === download.url
          );

          if (existingIndex >= 0) {
            this.downloads[existingIndex] = {
              ...this.downloads[existingIndex],
              ...download,
            };
          } else {
            this.downloads.push(download);
          }

          this.cleanupOldDownloads();
          this.updateDownloadsList();
        }

        updateDownloadsList() {
          if (this.downloads.length === 0) {
            this.downloadsList.innerHTML =
              '<p class="no-downloads">No active downloads. Submit URL above to initiate.</p>';
            return;
          }

          const sortedDownloads = [...this.downloads].sort((a, b) => {
            const timeA = a.lastUpdate || a.timestamp;
            const timeB = b.lastUpdate || b.timestamp;
            return timeB - timeA;
          });

          const downloadsHtml = sortedDownloads
            .map((download) => {
              const statusClass = `status-${download.status}`;
              const progressPercent = download.progress || 0;
              const showProgress =
                download.status === "downloading";

              let messageHtml = download.message || "Processing request";
              if (download.status === "completed" && download.downloadUrl) {
                messageHtml = `<strong>Download completed successfully</strong><br>
                        <div class="tiny-url-container" onclick="navigator.clipboard.writeText('${
                          download.downloadUrl
                        }'); this.querySelector('.tiny-url-value').style.color='#FFFF00'; setTimeout(() => this.querySelector('.tiny-url-value').style.color='#00FF00', 500);" title="Click to copy">
                            <span class="tiny-url-label">Tiny URL:</span>
                            <span class="tiny-url-value">${
                  download.downloadUrl
                }</span>
                        </div>
                        <a href="${
                          download.downloadUrl
                        }" target="_blank" rel="noopener noreferrer" class="download-link">${
                  download.fileName || "Download File"
                }</a>`;
              }

              return `
                        <div class="download-item ${statusClass}" data-id="${
                download.id
              }">
                            <div class="download-header">
                                <div class="download-url-container">
                                    <span class="download-url" title="${
                                      download.url
                                    }">${this.truncateUrl(download.url)}</span>
                                    <span class="download-timestamp">${this.formatTime(
                                      download.lastUpdate || download.timestamp
                                    )}</span>
                                </div>
                                <span class="status-badge ${statusClass}">${this.formatStatus(
                download.status
              )}</span>
                            </div>
                            
                            ${
                              showProgress
                                ? this.renderEnhancedProgressBar(download)
                                : ""
                            }
                            
                            <div class="download-details">
                                <div class="download-message">${messageHtml}</div>
                                ${this.renderDownloadMetadata(download)}
                            </div>
                        </div>
                    `;
            })
            .join("");

          this.downloadsList.innerHTML = downloadsHtml;
        }

        renderEnhancedProgressBar(download) {
          let progressPercent = download.progress || 0;
          if (download.status === "completed") {
            progressPercent = 100;
          }
          const progressTypeClass = download.progressType
            ? `progress-${download.progressType}`
            : "";
          const progressTypeIndicator = this.getProgressTypeIndicator(
            download.progressType
          );

          // Add classes for different states
          const activeClass = download.status === "downloading" ? "active" : "";
          const statusClass = `status-${download.status}`;
          const progressTextClass =
            download.status === "completed"
              ? "completed"
              : download.status === "error"
              ? "error"
              : "";

          // Build progress info line
          const progressInfo = [];
          if (download.downloadSpeed && download.status === "downloading") {
            progressInfo.push(`${download.downloadSpeed}`);
          }
          if (download.eta && download.status === "downloading") {
            progressInfo.push(`ETA ${download.eta}`);
          }
          if (download.fileSize) {
            progressInfo.push(`${download.fileSize}`);
          }

          const progressInfoText =
            progressInfo.length > 0 ? progressInfo.join(" • ") : "";

          return `
                    <div class="download-progress">
                        <div class="progress-header">
                            <div class="progress-info">
                                ${progressInfoText}
                                ${
                                  progressTypeIndicator
                                    ? `<span class="progress-type-indicator">${progressTypeIndicator}</span>`
                                    : ""
                                }
                            </div>
                            <div class="progress-text ${progressTextClass}">${progressPercent.toFixed(
            1
          )}%</div>
                        </div>
                        <div class="progress-bar ${progressTypeClass} ${activeClass} ${statusClass}">
                            <div class="progress-fill" style="width: ${progressPercent}%"></div>
                            <div class="progress-glow"></div>
                        </div>
                    </div>
                `;
        }

        getProgressTypeIndicator(progressType) {
          const indicators = {
            real: "[LIVE]",
            simulated: "[SIM]",
            hybrid: "[HYB]",
          };
          return indicators[progressType] || "";
        }

        renderDownloadMetadata(download) {
          const metadata = [];

          // Only show metadata that's not already in the progress bar
          if (download.fileName && download.status === "completed") {
            metadata.push(
              `<span class="metadata-item">File: ${download.fileName}</span>`
            );
          }

          if (download.progressTimestamp && download.status === "downloading") {
            const timeDiff = Math.floor(
              (new Date() - download.progressTimestamp) / 1000
            );
            if (timeDiff < 60) {
              metadata.push(
                `<span class="metadata-item">Updated: ${timeDiff}s ago</span>`
              );
            }
          }

          return metadata.length > 0
            ? `<div class="download-metadata">${metadata.join("")}</div>`
            : "";
        }

        formatStatus(status) {
          const statusMap = {
            pending: "Queued",
            downloading: "Active",
            completed: "Complete",
            error: "Error",
            failed: "Failed",
            cancelled: "Cancelled",
          };

          return statusMap[status] || status.toUpperCase();
        }

        showError(message) {
          this.showMessage(message, "error");
          this.urlInput.classList.add("error");
        }

        showSuccess(message) {
          this.showMessage(message, "success");
        }

        showMessage(message, type = "info") {
          const messageDiv = document.createElement("div");
          messageDiv.className = `message message-${type}`;
          messageDiv.textContent = message;

          const closeBtn = document.createElement("button");
          closeBtn.className = "message-close";
          closeBtn.innerHTML = "×";
          closeBtn.onclick = () => messageDiv.remove();
          messageDiv.appendChild(closeBtn);

          this.messagesArea.appendChild(messageDiv);

          setTimeout(() => {
            if (messageDiv.parentNode) {
              messageDiv.remove();
            }
          }, 5000);
        }

        clearValidationErrors() {
          this.urlInput.classList.remove("error");

          const existingError = this.form.querySelector(".validation-error");
          if (existingError) {
            existingError.remove();
          }
        }

        setFormState(enabled) {
          this.urlInput.disabled = !enabled;
          this.submitBtn.disabled = !enabled;

          if (enabled) {
            this.submitBtn.textContent = "> EXECUTE <";
          } else {
            this.submitBtn.innerHTML =
              '> PROCESSING <span class="loading-dots"></span>';
          }
        }

        generateDownloadId() {
          return (
            "dl_" +
            Date.now() +
            "_" +
            Math.random().toString(36).substring(2, 11)
          );
        }

        truncateUrl(url, maxLength = 60) {
          if (url.length <= maxLength) {
            return url;
          }
          return url.substring(0, maxLength - 3) + "...";
        }

        formatTime(timestamp) {
          const now = new Date();
          const diff = now - timestamp;

          if (diff < 60000) {
            return "now";
          }

          if (diff < 3600000) {
            const minutes = Math.floor(diff / 60000);
            return `${minutes}m`;
          }

          if (timestamp.toDateString() === now.toDateString()) {
            return timestamp.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            });
          }

          return timestamp.toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          });
        }

        cleanupOldDownloads() {
          const maxDownloads = 50;
          const maxAge = 24 * 60 * 60 * 1000; // 24 hours
          const now = new Date();

          this.downloads = this.downloads.filter((download, index) => {
            const age = now - (download.lastUpdate || download.timestamp);
            const isRecent = age < maxAge;
            const isInLimit = index < maxDownloads;

            if (
              download.status === "completed" ||
              download.status === "error"
            ) {
              return isRecent && isInLimit;
            }

            return true;
          });

          this.downloads.sort((a, b) => {
            const timeA = a.lastUpdate || a.timestamp;
            const timeB = b.lastUpdate || b.timestamp;
            return timeB - timeA;
          });
        }

        connectWebSocket() {
          if (!navigator.onLine) {
            this.updateConnectionStatus(
              "disconnected",
              "No Network Connection"
            );
            return;
          }

          this.updateConnectionStatus("connecting", "Establishing Connection");

          try {
            const protocol =
              window.location.protocol === "https:" ? "wss:" : "ws:";
            const wsUrl = `${protocol}//${window.location.host}/ws/${this.clientId}`;

            console.log("Connecting to WebSocket:", wsUrl);

            if (this.websocket) {
              this.websocket.close();
            }

            this.websocket = new WebSocket(wsUrl);

            const connectionTimeout = setTimeout(() => {
              if (
                this.websocket &&
                this.websocket.readyState === WebSocket.CONNECTING
              ) {
                console.log("WebSocket connection timeout");
                this.websocket.close();
                this.updateConnectionStatus(
                  "disconnected",
                  "Connection Timeout"
                );
                this.scheduleReconnect();
              }
            }, 10000);

            this.websocket.onopen = (event) => {
              clearTimeout(connectionTimeout);
              this.handleWebSocketOpen(event);
            };
            this.websocket.onmessage = (event) =>
              this.handleWebSocketMessage(event);
            this.websocket.onclose = (event) => {
              clearTimeout(connectionTimeout);
              this.handleWebSocketClose(event);
            };
            this.websocket.onerror = (event) => {
              clearTimeout(connectionTimeout);
              this.handleWebSocketError(event);
            };
          } catch (error) {
            console.error("Failed to create WebSocket connection:", error);
            this.updateConnectionStatus("disconnected", "Connection Failed");

            let errorMessage = "Connection establishment failed";
            if (error.name === "SecurityError") {
              errorMessage = "Connection blocked by security policy";
            } else if (error.message.includes("network")) {
              errorMessage = "Network error detected";
            }

            this.showError(errorMessage);
            this.scheduleReconnect();
          }
        }

        handleWebSocketOpen(event) {
          console.log("WebSocket connected successfully");
          this.updateConnectionStatus("connected", "Connection Established");

          this.reconnectAttempts = 0;
          this.reconnectDelay = 1000;

          if (this.reconnectMessage && this.reconnectMessage.parentNode) {
            this.reconnectMessage.remove();
            this.reconnectMessage = null;
          }

          this.hasBeenDisconnected = false;
        }

        handleWebSocketMessage(event) {
          try {
            const data = JSON.parse(event.data);
            console.log("WebSocket message received:", data);

            switch (data.type) {
              case "ping":
                this.websocket.send(JSON.stringify({ type: "pong" }));
                break;
              case "status":
              case "download_status":
              case "progress":
                this.handleStatusUpdate(data);
                break;
              case "connection":
                console.log("Connection message:", data.message);
                break;
              case "error":
                this.showError(
                  `System error: ${data.message || "Unknown error occurred"}`
                );
                break;
              case "info":
                if (data.message) {
                  this.showMessage(data.message, "info");
                }
                break;
              case "warning":
                if (data.message) {
                  this.showMessage(data.message, "warning");
                }
                break;
              default:
                if (data.message || data.url || data.progress !== undefined) {
                  this.handleStatusUpdate(data);
                } else {
                  console.log("Unknown message type:", data.type, data);
                }
            }
          } catch (error) {
            console.error(
              "Failed to parse WebSocket message:",
              error,
              "Raw data:",
              event.data
            );

            if (typeof event.data === "string" && event.data.trim()) {
              const message = event.data.trim();
              if (message.length > 0 && message.length < 500) {
                this.showMessage(`System: ${message}`, "info");
              }
            } else {
              console.warn("Received unparseable WebSocket message");
            }
          }
        }

        handleWebSocketClose(event) {
          console.log("WebSocket connection closed:", event.code, event.reason);

          this.hasBeenDisconnected = true;

          if (event.wasClean) {
            this.updateConnectionStatus(
              "disconnected",
              "Connection Terminated"
            );
          } else {
            this.updateConnectionStatus("disconnected", "Connection Lost");

            let errorMessage = "Connection lost. Attempting reconnect";
            switch (event.code) {
              case 1006:
                errorMessage = "Connection dropped unexpectedly. Reconnecting";
                break;
              case 1011:
                errorMessage = "Server error detected. Reconnecting";
                break;
              case 1012:
                errorMessage = "Server restart detected. Reconnecting";
                break;
            }

            if (this.reconnectAttempts === 0) {
              this.showMessage(errorMessage, "warning");
            }

            this.scheduleReconnect();
          }
        }

        handleWebSocketError(event) {
          console.error("WebSocket error:", event);
          this.updateConnectionStatus("disconnected", "Connection Error");

          if (this.reconnectAttempts === 0) {
            this.showError("Connection error detected. Attempting recovery");
          }
        }

        handleStatusUpdate(data) {
          console.log("Status update received:", data);

          const {
            message,
            client_id,
            progress,
            url,
            status,
            download_id,
            file_name,
            download_url,
          } = data;

          if (client_id && client_id !== this.clientId) {
            return;
          }

          let download = null;
          let downloadIndex = -1;

          if (download_id) {
            downloadIndex = this.downloads.findIndex(
              (d) => d.id === download_id
            );
          }

          if (downloadIndex === -1 && url) {
            downloadIndex = this.downloads.findIndex((d) => d.url === url);
          }

          if (downloadIndex === -1 && !url) {
            downloadIndex = this.downloads.findIndex(
              (d) =>
                ["pending", "downloading", "processing"].includes(d.status) &&
                new Date() - d.timestamp < 300000
            );
          }

          if (downloadIndex >= 0) {
            download = this.downloads[downloadIndex];
          } else if (url) {
            download = {
              id: download_id || this.generateDownloadId(),
              url: url,
              status: "pending",
              progress: 0,
              message: "Download initiated",
              timestamp: new Date(),
              fakeProgressActive: false,
              progressHistory: [],
            };
            this.downloads.push(download);
            downloadIndex = this.downloads.length - 1;
          } else {
            if (message) {
              this.showMessage(`System: ${message}`, "info");
            }
            return;
          }

          if (download) {
            // Handle enhanced progress data
            this.processEnhancedProgressData(download, data);

            // Stop fake progress when real data arrives
            if (
              typeof progress === "number" ||
              status === "completed" ||
              status === "error"
            ) {
              this.stopFakeProgress(download);
            }

            if (status) {
              download.status = status.toLowerCase();

              // Clean up animations when download completes
              if (status === "completed" || status === "error") {
                this.cleanupProgressAnimation(download.id);
              }
            }

            if (typeof progress === "number") {
              const newProgress = Math.max(0, Math.min(100, progress));
              this.updateProgressWithVisualFeedback(download, newProgress);
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

            download.lastUpdate = new Date();

            this.updateDownloadsList();
          }
        }

        processEnhancedProgressData(download, data) {
          // Handle enhanced progress metadata
          if (data.download_speed) {
            download.downloadSpeed = data.download_speed;
          }

          if (data.eta) {
            download.eta = data.eta;
          }

          if (data.file_size) {
            download.fileSize = data.file_size;
          }

          // Handle progress type indicator
          if (data.progress_type) {
            download.progressType = data.progress_type;
          }

          // Handle timestamp for progress tracking
          if (data.timestamp) {
            download.progressTimestamp = new Date(data.timestamp);
          }

          // Store progress history for smoothing
          if (typeof data.progress === "number") {
            if (!download.progressHistory) {
              download.progressHistory = [];
            }

            download.progressHistory.push({
              progress: data.progress,
              timestamp: new Date(),
              type: data.progress_type || "unknown",
            });

            // Keep only last 10 progress updates for smoothing
            if (download.progressHistory.length > 10) {
              download.progressHistory = download.progressHistory.slice(-10);
            }
          }
        }

        updateProgressWithSmoothing(download, newProgress) {
          const currentProgress = download.progress || 0;
          const progressDiff = Math.abs(newProgress - currentProgress);

          // Use smooth animation for significant progress jumps
          if (progressDiff > 2 && download.status === "downloading") {
            this.updateProgressSmoothly(download.id, newProgress);
          } else {
            download.progress = newProgress;
          }
        }

        // Enhanced smooth progress updates with easing
        updateProgressSmoothly(downloadId, targetProgress, duration = 1000) {
          if (!this.smoothProgress[downloadId]) {
            this.smoothProgress[downloadId] = {
              current: 0,
              target: 0,
              animation: null,
            };
          }

          const download = this.downloads.find((d) => d.id === downloadId);
          if (!download) return;

          const progressData = this.smoothProgress[downloadId];
          progressData.target = targetProgress;
          progressData.current = download.progress || 0;

          // Cancel existing animation if any
          if (progressData.animation) {
            cancelAnimationFrame(progressData.animation);
          }

          const startTime = performance.now();
          const startProgress = progressData.current;

          const animate = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);

            // Use easing function for smooth animation
            const easedProgress = this.easeOutCubic(progress);
            progressData.current =
              startProgress + (targetProgress - startProgress) * easedProgress;

            // Update the download progress
            if (download) {
              download.progress = progressData.current;
              this.updateDownloadsList();
            }

            // Continue animation if not complete
            if (progress < 1 && download.status === "downloading") {
              progressData.animation = requestAnimationFrame(animate);
            } else {
              progressData.animation = null;
            }
          };

          progressData.animation = requestAnimationFrame(animate);
        }

        // Easing functions for smooth animations
        easeOutCubic(t) {
          return 1 - Math.pow(1 - t, 3);
        }

        easeInOutQuad(t) {
          return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
        }

        // Clean up progress animations when download completes
        cleanupProgressAnimation(downloadId) {
          if (
            this.smoothProgress[downloadId] &&
            this.smoothProgress[downloadId].animation
          ) {
            cancelAnimationFrame(this.smoothProgress[downloadId].animation);
          }
          delete this.smoothProgress[downloadId];
        }

        // Add micro-animations for small progress updates
        addProgressMicroAnimation(downloadId) {
          const progressBar = document.querySelector(
            `[data-id="${downloadId}"] .progress-fill`
          );
          if (progressBar) {
            progressBar.style.transform = "scaleX(1.02)";
            setTimeout(() => {
              if (progressBar) {
                progressBar.style.transform = "scaleX(1)";
              }
            }, 150);
          }
        }

        // Enhanced progress update with visual feedback
        updateProgressWithVisualFeedback(download, newProgress) {
          const oldProgress = download.progress || 0;
          const progressDiff = newProgress - oldProgress;

          // Update progress
          this.updateProgressWithSmoothing(download, newProgress);

          // Add visual feedback for progress updates
          if (progressDiff > 0 && progressDiff < 5) {
            setTimeout(() => this.addProgressMicroAnimation(download.id), 100);
          }
        }

        updateConnectionStatus(status, text) {
          this.connectionStatus.className = `status-indicator ${status}`;
          this.connectionText.textContent = text;
        }

        scheduleReconnect() {
          if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.updateConnectionStatus(
              "disconnected",
              "Max Reconnect Attempts Reached"
            );
            this.showError("Connection failed. Manual intervention required.");
            return;
          }

          this.reconnectAttempts++;
          const delay = Math.min(
            this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxReconnectDelay
          );

          this.updateConnectionStatus(
            "connecting",
            `Reconnect Attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts}`
          );

          setTimeout(() => {
            this.connectWebSocket();
          }, delay);
        }

        manualReconnect() {
          this.reconnectAttempts = 0;
          this.connectWebSocket();
        }
      }

      // Initialize the download manager when the page loads
      document.addEventListener("DOMContentLoaded", () => {
        if (window.CLIENT_ID) {
          window.downloadManager = new DownloadManager(window.CLIENT_ID);
        } else {
          console.error("CLIENT_ID not found");
        }
      });
    