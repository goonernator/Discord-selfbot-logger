class DashboardApp {
    constructor() {
        this.socket = io();
        this.currentFilter = 'all';
        this.currentView = 'dashboard';
        this.currentLayout = localStorage.getItem('selectedLayout') || 'modern';
        this.currentTheme = localStorage.getItem('selectedTheme') || 'default';
        this.events = [];
        this.stats = {};
        this.accounts = {};
        this.selectedAccountId = 'current';
        this.activityChart = null;
        
        this.applyLayout(this.currentLayout);
        this.applyTheme(this.currentTheme);
        this.initializeEventListeners();
        this.initializeWebSocket();
        this.loadInitialData();
        this.startPeriodicUpdates();
        this.initializeActivityChart();
    }

    setLayout(layoutName) {
        this.currentLayout = layoutName;
        localStorage.setItem('selectedLayout', layoutName);
        this.applyLayout(layoutName);
        showToast('Layout Changed', `Interface layout set to ${layoutName}`, 'success');
    }

    applyLayout(layoutName) {
        document.body.classList.remove('layout-modern', 'layout-legacy', 'layout-discord');
        document.body.classList.add(`layout-${layoutName}`);
        
        const selector = document.getElementById('layoutSelector');
        if (selector) selector.value = layoutName;
    }

    setTheme(themeName) {
        this.currentTheme = themeName;
        localStorage.setItem('selectedTheme', themeName);
        this.applyTheme(themeName);
        
        // Update theme options UI
        document.querySelectorAll('.theme-option').forEach(option => {
            if (option.dataset.theme === themeName) {
                option.classList.add('active');
            } else {
                option.classList.remove('active');
            }
        });
        
        showNotification(`Theme changed to ${themeName.charAt(0).toUpperCase() + themeName.slice(1)}`, 'success');
    }

    applyTheme(themeName) {
        if (themeName === 'default') {
            document.documentElement.removeAttribute('data-theme');
        } else {
            document.documentElement.setAttribute('data-theme', themeName);
        }
    }

    initializeActivityChart() {
        const ctx = document.getElementById('activityChart');
        if (!ctx) return;

        this.activityChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Events',
                    data: [],
                    borderColor: '#5865f2',
                    backgroundColor: 'rgba(88, 101, 242, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0,0,0,0.05)' }
                    },
                    x: {
                        grid: { display: false }
                    }
                }
            }
        });
    }

    updateActivityChart() {
        if (!this.activityChart) return;

        // Group events by time (last 10 minutes)
        const now = new Date();
        const buckets = {};
        for (let i = 0; i < 10; i++) {
            const time = new Date(now.getTime() - i * 60000);
            const label = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            buckets[label] = 0;
        }

        this.events.forEach(event => {
            const eventTime = new Date(event.timestamp);
            const label = eventTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            if (buckets.hasOwnProperty(label)) {
                buckets[label]++;
            }
        });

        const labels = Object.keys(buckets).reverse();
        const data = labels.map(label => buckets[label]);

        this.activityChart.data.labels = labels;
        this.activityChart.data.datasets[0].data = data;
        this.activityChart.update();
    }

    initializeEventListeners() {
        // Sidebar navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const view = item.dataset.view;
                if (view) this.switchView(view);
            });
        });

        // Filter tabs
        document.querySelectorAll('.filter-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                this.setActiveFilter(e.target.dataset.filter);
            });
        });

        // Account selector
        const accountSelect = document.getElementById('accountSelect');
        if (accountSelect) {
            accountSelect.addEventListener('change', (e) => {
                this.selectedAccountId = e.target.value;
                this.loadEventsForAccount();
            });
        }
    }

    switchView(viewId) {
        this.currentView = viewId;
        
        // Update sidebar UI
        document.querySelectorAll('.nav-item').forEach(item => {
            if (item.dataset.view === viewId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        // Update view title
        const titles = {
            'dashboard': 'Dashboard',
            'events': 'All Events',
            'attachments': 'Attachments',
            'accounts': 'Account Management',
            'settings': 'Settings'
        };
        const titleElement = document.getElementById('currentViewTitle');
        if (titleElement) titleElement.textContent = titles[viewId] || 'View';

        // Update content visibility
        document.querySelectorAll('.view-content').forEach(view => {
            if (view.id === `${viewId}-view`) {
                view.classList.add('active');
            } else {
                view.classList.remove('active');
            }
        });

        // Special handling for views
        if (viewId === 'events') {
            this.renderEvents();
        } else if (viewId === 'dashboard') {
            this.renderRecentEvents();
            this.updateActivityChart();
        } else if (viewId === 'attachments') {
            this.renderAttachments();
        } else if (viewId === 'accounts') {
            this.renderAccountsView();
        } else if (viewId === 'settings') {
            this.renderSettingsView();
        }
    }

    renderAttachments() {
        const container = document.getElementById('attachmentsList');
        if (!container) return;

        const attachmentEvents = this.events.filter(event => 
            event.data && event.data.attachments && event.data.attachments.length > 0
        );

        if (attachmentEvents.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-paperclip"></i>
                    <span>No attachments found yet</span>
                </div>
            `;
            return;
        }

        container.innerHTML = attachmentEvents.map(event => this.renderEvent(event)).join('');
        this.addEventHandlers(container, attachmentEvents);
    }

    renderAccountsView() {
        // This is handled by loadAccounts() which updates the UI
        loadAccounts();
    }

    renderSettingsView() {
        // This is handled by loadSettings() and loadDuplicates()
        loadSettings();
        loadDuplicates();
        loadCurrentLogLevel();
    }

    addEventHandlers(container, events) {
        container.querySelectorAll('.event-item').forEach((eventElement, index) => {
            const event = events[index];
            const data = event.data || {};
            
            eventElement._eventData = {
                channel_id: data.channel_id,
                channel_name: data.channel_name || data.guild_name || 'Unknown Channel',
                author: data.author || data.username || 'Unknown User',
                event_type: event.type,
                timestamp: event.timestamp
            };
            
            eventElement.addEventListener('click', (e) => {
                if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
                    return;
                }
                eventElement.classList.toggle('expanded');
            });
            
            eventElement.addEventListener('contextmenu', (e) => {
                if (event.type === 'message' || event.type === 'mention') {
                    showContextMenu(e, eventElement._eventData);
                }
            });
        });
        updateEventDisplays();
    }

    renderRecentEvents() {
        const container = document.getElementById('recentEventsList');
        if (!container) return;

        const recentEvents = this.events.slice(0, 5);
        if (recentEvents.length === 0) {
            container.innerHTML = '<div class="no-events">No recent activity</div>';
            return;
        }

        container.innerHTML = recentEvents.map(event => this.renderEvent(event)).join('');
    }

    populateDiscordSidebar() {
        const container = document.getElementById('discordServerList');
        if (!container) return;

        container.innerHTML = '';
        Object.entries(this.accounts).forEach(([accountId, accountData]) => {
            const icon = document.createElement('div');
            icon.className = `server-icon ${accountData.is_current ? 'active' : ''}`;
            icon.title = accountData.name;
            icon.innerHTML = accountData.name.charAt(0).toUpperCase();
            icon.onclick = () => {
                this.selectedAccountId = accountId;
                this.loadEventsForAccount();
                this.populateDiscordSidebar();
            };
            container.appendChild(icon);
        });
    }

    initializeWebSocket() {
        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.updateConnectionStatus(true);
            this.socket.emit('request_status');
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
            this.updateConnectionStatus(false);
        });

        this.socket.on('new_event', (event) => {
            this.addNewEvent(event);
        });

        this.socket.on('status_update', (data) => {
            this.updateStats(data);
        });

        this.socket.on('error', (error) => {
            console.error('Socket error:', error);
        });
    }

    async loadInitialData() {
        try {
            // Load accounts first
            await this.loadAccounts();
            this.populateDiscordSidebar();

            // Load events for current account
            await this.loadEventsForAccount();

            // Load status
            const statusResponse = await fetch('/api/status');
            const statusData = await statusResponse.json();
            this.updateStats(statusData);
            this.updateRateLimits(statusData.rate_limits);

            // Load current account info
            await this.loadCurrentAccount();

        } catch (error) {
            console.error('Error loading initial data:', error);
        }
    }

    async loadAccounts() {
        try {
            const response = await fetch('/api/events/accounts');
            const data = await response.json();
            this.accounts = data.accounts || {};
            this.populateAccountSelector(data.current_account);
        } catch (error) {
            console.error('Error loading accounts:', error);
        }
    }

    populateAccountSelector(currentAccountId) {
        const accountSelect = document.getElementById('accountSelect');
        if (!accountSelect) return;

        // Clear existing options except "Current Account"
        accountSelect.innerHTML = '<option value="current">Current Account</option>';

        // Add options for each account
        Object.entries(this.accounts).forEach(([accountId, accountData]) => {
            const option = document.createElement('option');
            option.value = accountId;
            option.textContent = `${accountData.name} (${accountData.event_count} events)`;
            if (accountData.is_current) {
                option.textContent += ' - Active';
            }
            accountSelect.appendChild(option);
        });
    }

    async loadEventsForAccount() {
        try {
            let url;
            if (this.selectedAccountId === 'current') {
                url = '/api/events?limit=50';
            } else {
                url = `/api/events/account/${this.selectedAccountId}?limit=50`;
            }

                    const response = await fetch(url);
                    const data = await response.json();
                    this.events = data.events || [];
                    
                    if (this.currentView === 'dashboard') {
                        this.renderRecentEvents();
                        this.updateActivityChart();
                    } else {
                        this.renderEvents();
                    }

            // Update account info display if available
            if (data.account_name && this.selectedAccountId !== 'current') {
                const sectionTitle = document.querySelector('.section-title');
                if (sectionTitle) {
                    sectionTitle.textContent = `Recent Events - ${data.account_name}`;
                }
            } else {
                const sectionTitle = document.querySelector('.section-title');
                if (sectionTitle) {
                    sectionTitle.textContent = 'Recent Events';
                }
            }
        } catch (error) {
            console.error('Error loading events for account:', error);
        }
    }

    startPeriodicUpdates() {
        // Update status every 1 second for real-time updates
        setInterval(() => {
            this.loadStatus();
        }, 1000);
    }

    async loadStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();
            this.updateStats(data);
            this.updateRateLimits(data.rate_limits);
            
            // Also update user profile for real-time status changes
            try {
                const profileResponse = await fetch('/api/user/profile');
                const profileData = await profileResponse.json();
                if (profileData.success && profileData.user) {
                    this.updateUserProfile(profileData.user);
                }
            } catch (profileError) {
                // Silently fail profile updates to not interfere with main status
                console.debug('Profile update failed:', profileError);
            }
        } catch (error) {
            console.error('Error loading status:', error);
        }
    }

    updateStats(data) {
        if (data.events) {
            document.getElementById('messagesCount').textContent = data.events.messages || 0;
            document.getElementById('mentionsCount').textContent = data.events.mentions || 0;
            document.getElementById('deletionsCount').textContent = data.events.deletions || 0;
            document.getElementById('friendsCount').textContent = data.events.friends || 0;
        }

        if (data.uptime) {
            document.getElementById('uptimeValue').textContent = data.uptime;
        }
    }

    updateRateLimits(rateLimits) {
        if (!rateLimits) return;

        const indicators = {
            webhook: document.getElementById('webhookRateIndicator'),
            api: document.getElementById('apiRateIndicator'),
            download: document.getElementById('downloadRateIndicator')
        };

        Object.keys(rateLimits).forEach(key => {
            const indicator = indicators[key];
            if (indicator) {
                indicator.className = `rate-limit-indicator ${
                    rateLimits[key] ? 'rate-limit-ok' : 'rate-limit-limited'
                }`;
            }
        });
    }

    updateConnectionStatus(connected) {
        const status = document.getElementById('connectionStatus');
        const statusText = document.getElementById('connectionStatusText');
        
        if (connected) {
            if (status) {
                status.className = 'connection-indicator connected';
                status.innerHTML = '<i class="fas fa-wifi"></i><span>Connected</span>';
            }
            if (statusText) statusText.textContent = 'Online';
        } else {
            if (status) {
                status.className = 'connection-indicator disconnected';
                status.innerHTML = '<i class="fas fa-wifi"></i><span>Disconnected</span>';
            }
            if (statusText) statusText.textContent = 'Offline';
        }
    }

    setActiveFilter(filter) {
        this.currentFilter = filter;
        
        // Update tab appearance
        document.querySelectorAll('.filter-tab').forEach(tab => {
            tab.classList.remove('active');
        });
        document.querySelector(`[data-filter="${filter}"]`).classList.add('active');
        
        // Re-render events
        this.renderEvents();
    }

    addNewEvent(event) {
        this.events.unshift(event);
        if (this.events.length > 100) {
            this.events.pop();
        }
        
        if (this.currentView === 'dashboard') {
            this.renderRecentEvents();
            this.updateActivityChart();
        } else if (this.currentView === 'events') {
            this.renderEvents();
        }
    }

    renderEvents() {
        const container = document.getElementById('eventsList');
        let filteredEvents;
        
        if (this.currentFilter === 'all') {
            filteredEvents = this.events;
        } else if (this.currentFilter === 'favourites') {
            filteredEvents = this.events.filter(event => {
                const author = event.data?.author || event.data?.username;
                return author && userPreferences.favoriteUsers.has(author);
            });
        } else if (this.currentFilter === 'attachments') {
            filteredEvents = this.events.filter(event => {
                return event.data && event.data.attachments && event.data.attachments.length > 0;
            });
        } else {
            filteredEvents = this.events.filter(event => event.type === this.currentFilter);
        }

        if (filteredEvents.length === 0) {
            let emptyMessage = 'No events yet';
            let emptyIcon = 'fas fa-inbox';
            
            if (this.currentFilter === 'favourites') {
                emptyMessage = 'No events from favorited users yet';
                emptyIcon = 'fas fa-star';
            } else if (this.currentFilter === 'attachments') {
                emptyMessage = 'No events with attachments yet';
                emptyIcon = 'fas fa-paperclip';
            } else if (this.currentFilter !== 'all') {
                emptyMessage = `No ${this.currentFilter} events yet`;
            }
            
            container.innerHTML = `
                <div class="empty-state">
                    <i class="${emptyIcon}"></i>
                    <span>${emptyMessage}</span>
                </div>
            `;
            return;
        }

        container.innerHTML = filteredEvents.map(event => this.renderEvent(event)).join('');
        this.addEventHandlers(container, filteredEvents);
    }

    renderEvent(event) {
        const icons = {
            message: 'fas fa-comment',
            mention: 'fas fa-at',
            deletion: 'fas fa-trash',
            friend: 'fas fa-user-plus'
        };

        const time = new Date(event.timestamp).toLocaleTimeString();
        const data = event.data || {};
        const expandedContent = this.createExpandedContent(event);

        const eventHtml = `
            <div class="event-item ${event.type} animate__animated animate__fadeInUp">
                <div class="event-icon ${event.type}">
                    <i class="${icons[event.type] || 'fas fa-info'}"></i>
                </div>
                <div class="event-content">
                    <div class="event-title">${this.getEventTitle(event)}</div>
                    <div class="event-description">${this.getEventDescription(event)}</div>
                    <div class="event-time">${time}</div>
                    ${expandedContent}
                </div>
                <div class="expand-indicator">
                    <i class="fas fa-chevron-down"></i>
                </div>
            </div>
        `;
        
        return eventHtml;
    }

    getEventTitle(event) {
        const titles = {
            message: 'New Message',
            mention: 'Mention Detected',
            deletion: 'Message Deleted',
            friend: 'Relationship Update'
        };
        return titles[event.type] || 'Event';
    }

    getEventDescription(event) {
        const data = event.data || {};
        const maxLength = 100;
        let content = '';
        
        switch (event.type) {
            case 'message':
                // Check if message only contains attachments
                const hasAttachments = data.attachments && data.attachments.length > 0;
                const hasContent = data.content && data.content.trim().length > 0;
                
                if (hasAttachments && !hasContent) {
                    return `<strong>${data.author || 'Unknown'}</strong>: <em>Attachment Received</em>`;
                }
                
                content = data.content || '<em>No content</em>';
                if (content.length > maxLength) {
                    content = content.substring(0, maxLength) + '...';
                }
                return `<strong>${data.author || 'Unknown'}</strong>: ${content}`;
            case 'mention':
                // Check if mention only contains attachments
                const mentionHasAttachments = data.attachments && data.attachments.length > 0;
                const mentionHasContent = data.content && data.content.trim().length > 0;
                
                if (mentionHasAttachments && !mentionHasContent) {
                    return `<strong>${data.author || 'Unknown'}</strong> mentioned you: <em>Attachment Received</em>`;
                }
                
                content = data.content || '<em>No content</em>';
                if (content.length > maxLength) {
                    content = content.substring(0, maxLength) + '...';
                }
                return `<strong>${data.author || 'Unknown'}</strong> mentioned you: ${content}`;
            case 'deletion':
                content = data.content || '<em>No content</em>';
                if (content.length > maxLength) {
                    content = content.substring(0, maxLength) + '...';
                }
                return `Message deleted by <strong>${data.author || 'Unknown'}</strong>: ${content}`;
            case 'friend':
                const relationshipType = data.relationship_type || 'relationship';
                const displayName = data.display_name ? ` (${data.display_name})` : '';
                const username = data.username || data.user_tag || 'Unknown User';
                return `${relationshipType} ${data.action || 'updated'}: <strong>${username}${displayName}</strong>`;
            default:
                return JSON.stringify(data);
        }
    }

    createExpandedContent(event) {
        let expandedHtml = '<div class="event-expanded-content">';
        
        // Relationship-specific content
        if (event.type === 'friend') {
            expandedHtml += '<div class="relationship-profile">';
            
            // Profile picture
            if (event.data.avatar_url) {
                expandedHtml += `
                    <div class="profile-avatar">
                        <img src="${event.data.avatar_url}" alt="${this.escapeHtml(event.data.username || 'User')}" 
                             class="avatar-image" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                        <div class="avatar-fallback" style="display: none;">
                            <i class="fas fa-user"></i>
                        </div>
                    </div>
                `;
            } else {
                expandedHtml += `
                    <div class="profile-avatar">
                        <div class="avatar-fallback">
                            <i class="fas fa-user"></i>
                        </div>
                    </div>
                `;
            }
            
            // User information
            expandedHtml += '<div class="profile-info">';
            if (event.data.display_name) {
                expandedHtml += `<div class="profile-display-name">${this.escapeHtml(event.data.display_name)}</div>`;
            }
            expandedHtml += `<div class="profile-username">@${this.escapeHtml(event.data.username || 'unknown')}</div>`;
            if (event.data.discriminator && event.data.discriminator !== '0000') {
                expandedHtml += `<div class="profile-discriminator">#${event.data.discriminator}</div>`;
            }
            expandedHtml += '</div>';
            
            expandedHtml += '</div>';
        }
        
        // Full message content
        if (event.data.content) {
            expandedHtml += `
                <div class="event-full-content">${this.escapeHtml(event.data.content)}</div>
            `;
        }
        
        // Metadata
        expandedHtml += '<div class="event-metadata">';
        
        if (event.data.channel_name) {
            expandedHtml += `
                <div class="metadata-item">
                    <div class="metadata-label">Channel:</div>
                    <div>${this.escapeHtml(event.data.channel_name)}</div>
                </div>
            `;
        }
        
        if (event.data.guild) {
            expandedHtml += `
                <div class="metadata-item">
                    <div class="metadata-label">Server:</div>
                    <div>${this.escapeHtml(event.data.guild)}</div>
                </div>
            `;
        }
        
        expandedHtml += `
            <div class="metadata-item">
                <div class="metadata-label">Timestamp:</div>
                <div>${new Date(event.timestamp).toLocaleString()}</div>
            </div>
        `;
        
        if (event.data.message_id) {
            expandedHtml += `
                <div class="metadata-item">
                    <div class="metadata-label">Message ID:</div>
                    <div>${event.data.message_id}</div>
                </div>
            `;
        }
        
        expandedHtml += '</div>';
        
        // Attachments
        if (event.data.attachments && event.data.attachments.length > 0) {
            expandedHtml += '<div class="attachments-section">';
            expandedHtml += '<h4>Attachments:</h4>';
            
            event.data.attachments.forEach(attachment => {
                expandedHtml += this.createAttachmentHtml(attachment);
            });
            
            expandedHtml += '</div>';
        }
        
        expandedHtml += '</div>';
        return expandedHtml;
    }

    createAttachmentHtml(attachment) {
        const filename = attachment.filename || 'unknown_file';
        const fileSize = this.formatFileSize(attachment.size || 0);
        
        // Determine if it's an image based on content_type OR file extension
        const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'];
        const videoExtensions = ['mp4', 'mov', 'avi', 'mkv', 'webm'];
        const ext = filename.toLowerCase().split('.').pop() || '';
        
        const isImage = (attachment.content_type && attachment.content_type.startsWith('image/')) || 
                        imageExtensions.includes(ext);
        const isVideo = (attachment.content_type && attachment.content_type.startsWith('video/')) || 
                        videoExtensions.includes(ext);
        
        // Use local download endpoint for saved attachments, with Discord URL as fallback
        const localUrl = `/api/attachments/download/${encodeURIComponent(filename)}`;
        const discordUrl = attachment.url || attachment.proxy_url || '';
        
        // For display, prefer Discord URL first (faster/always available), fall back to local
        const displayUrl = discordUrl || localUrl;
        // For download, prefer local if available
        const downloadUrl = localUrl;
        
        let attachmentHtml = '<div class="attachment-item">';
        
        if (isImage && filename) {
            attachmentHtml += `
                <img src="${displayUrl}" alt="${this.escapeHtml(filename)}" 
                     class="attachment-preview" 
                     onclick="dashboardApp.openImageModal('${displayUrl}', '${this.escapeHtml(filename)}')"
                     onerror="this.onerror=null; this.src='${localUrl}';">
            `;
        } else if (isVideo && filename) {
            // For videos, show a video thumbnail or player
            attachmentHtml += `
                <div class="attachment-preview video-preview" onclick="dashboardApp.openVideoModal('${displayUrl}', '${this.escapeHtml(filename)}')">
                    <video src="${displayUrl}" preload="metadata" style="width: 100%; height: 100%; object-fit: cover; border-radius: 8px;">
                    </video>
                    <div class="video-play-overlay">
                        <i class="fas fa-play-circle"></i>
                    </div>
                </div>
            `;
        } else {
            // Generic file icon for other types
            const iconClass = this.getFileIcon(ext);
            attachmentHtml += `
                <div class="attachment-preview file-preview" style="background: var(--hover-bg); display: flex; align-items: center; justify-content: center;">
                    <i class="${iconClass}" style="font-size: 24px; color: var(--text-secondary);"></i>
                </div>
            `;
        }
        
        attachmentHtml += `
            <div class="attachment-info">
                <div class="attachment-name">${this.escapeHtml(filename)}</div>
                <div class="attachment-size">${fileSize}</div>
            </div>
        `;
        
        if (filename) {
            attachmentHtml += `
                <a href="${downloadUrl}" target="_blank" class="attachment-download" title="Download from local storage">
                    <i class="fas fa-download"></i> Download
                </a>
            `;
        }
        
        attachmentHtml += '</div>';
        return attachmentHtml;
    }

    getFileIcon(ext) {
        const iconMap = {
            // Documents
            'pdf': 'fas fa-file-pdf',
            'doc': 'fas fa-file-word',
            'docx': 'fas fa-file-word',
            'xls': 'fas fa-file-excel',
            'xlsx': 'fas fa-file-excel',
            'ppt': 'fas fa-file-powerpoint',
            'pptx': 'fas fa-file-powerpoint',
            'txt': 'fas fa-file-alt',
            // Archives
            'zip': 'fas fa-file-archive',
            'rar': 'fas fa-file-archive',
            '7z': 'fas fa-file-archive',
            'tar': 'fas fa-file-archive',
            'gz': 'fas fa-file-archive',
            // Audio
            'mp3': 'fas fa-file-audio',
            'wav': 'fas fa-file-audio',
            'ogg': 'fas fa-file-audio',
            'flac': 'fas fa-file-audio',
            // Code
            'js': 'fas fa-file-code',
            'py': 'fas fa-file-code',
            'html': 'fas fa-file-code',
            'css': 'fas fa-file-code',
            'json': 'fas fa-file-code',
        };
        return iconMap[ext] || 'fas fa-file';
    }

    openVideoModal(url, filename) {
        const modal = document.createElement('div');
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            cursor: pointer;
        `;
        
        const video = document.createElement('video');
        video.src = url;
        video.controls = true;
        video.autoplay = true;
        video.style.cssText = `
            max-width: 90%;
            max-height: 90%;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        `;
        
        const closeBtn = document.createElement('button');
        closeBtn.innerHTML = '<i class="fas fa-times"></i>';
        closeBtn.style.cssText = `
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(255, 255, 255, 0.2);
            border: none;
            color: white;
            font-size: 24px;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        
        modal.appendChild(video);
        modal.appendChild(closeBtn);
        document.body.appendChild(modal);
        
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            video.pause();
            document.body.removeChild(modal);
        });
        
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                video.pause();
                document.body.removeChild(modal);
            }
        });
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    openImageModal(url, filename) {
        const modal = document.createElement('div');
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            cursor: pointer;
        `;
        
        const img = document.createElement('img');
        img.src = url;
        img.alt = filename;
        img.style.cssText = `
            max-width: 90%;
            max-height: 90%;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        `;
        
        modal.appendChild(img);
        document.body.appendChild(modal);
        
        modal.addEventListener('click', () => {
            document.body.removeChild(modal);
        });
    }

    async loadCurrentAccount() {
        try {
            // Load user profile with avatar and status
            const profileResponse = await fetch('/api/user/profile');
            const profileData = await profileResponse.json();
            
            if (profileData.success && profileData.user) {
                this.updateUserProfile(profileData.user);
            } else {
                // Fallback to accounts API
                const response = await fetch('/api/accounts');
                const data = await response.json();
                
                if (data.success && data.accounts && Object.keys(data.accounts).length > 0) {
                    const activeAccount = Object.values(data.accounts).find(acc => acc.active) || Object.values(data.accounts)[0];
                    this.updateAccountIndicator(activeAccount);
                    this.showAvatarFallback(); // Show fallback avatar when Discord client unavailable
                } else {
                    this.updateAccountIndicator(null);
                    this.showAvatarFallback(); // Show fallback avatar when no accounts
                }
            }
        } catch (error) {
            console.error('Error loading current account:', error);
            this.updateAccountIndicator(null);
            this.showAvatarFallback(); // Show fallback avatar on error
        }
    }

    updateUserProfile(user) {
        // Update profile name
        const nameElement = document.getElementById('currentAccountName');
        const displayName = user.global_name || user.username || 'Unknown User';
        nameElement.textContent = displayName;
        
        // Update profile avatar
        const avatarImg = document.getElementById('profileAvatarImg');
        const avatarFallback = document.getElementById('profileAvatarFallback');
        
        if (user.avatar_url) {
            avatarImg.src = user.avatar_url;
            avatarImg.style.display = 'block';
            avatarFallback.style.display = 'none';
            
            // Handle image load error
            avatarImg.onerror = () => {
                avatarImg.style.display = 'none';
                avatarFallback.style.display = 'flex';
            };
        } else {
            avatarImg.style.display = 'none';
            avatarFallback.style.display = 'flex';
        }
        
        // Update status
        const statusSpan = document.querySelector('.profile-status span');
        const statusDot = document.querySelector('.status-dot');
        
        if (statusSpan && statusDot) {
            const statusText = this.getStatusText(user.status);
            const statusColor = this.getStatusColor(user.status);
            
            statusSpan.textContent = statusText;
            statusDot.style.color = statusColor;
        }
    }
    
    getStatusText(status) {
        const statusMap = {
            'online': 'Online',
            'idle': 'Away',
            'dnd': 'Do Not Disturb',
            'offline': 'Offline',
            'invisible': 'Invisible'
        };
        return statusMap[status] || 'Unknown';
    }
    
    getStatusColor(status) {
        const colorMap = {
            'online': 'var(--success-color)',
            'idle': 'var(--warning-color)',
            'dnd': 'var(--danger-color)',
            'offline': 'var(--secondary-color)',
            'invisible': 'var(--secondary-color)'
        };
        return colorMap[status] || 'var(--secondary-color)';
    }

    updateAccountIndicator(account) {
        const indicator = document.getElementById('currentAccountName');
        if (account) {
            indicator.textContent = account.name || account.username || 'Unknown Account';
            indicator.parentElement.style.display = 'inline-flex';
        } else {
            indicator.textContent = 'No Account';
            indicator.parentElement.style.display = 'inline-flex';
        }
    }

    showAvatarFallback() {
        // Hide profile image and show fallback avatar
        const avatarImg = document.getElementById('profileAvatarImg');
        const avatarFallback = document.getElementById('profileAvatarFallback');
        
        if (avatarImg && avatarFallback) {
            avatarImg.style.display = 'none';
            avatarFallback.style.display = 'flex';
        }
    }
}

// Simple account loader function
async function loadAccountName() {
    try {
        const response = await fetch('/api/accounts');
        const data = await response.json();
        const indicator = document.getElementById('currentAccountName');
        
        if (data.success && data.accounts && Object.keys(data.accounts).length > 0) {
            const activeAccount = Object.values(data.accounts).find(acc => acc.active) || Object.values(data.accounts)[0];
            indicator.textContent = activeAccount.name || 'Unknown Account';
        } else {
            indicator.textContent = 'No Account';
        }
    } catch (error) {
        console.error('Error loading account:', error);
        document.getElementById('currentAccountName').textContent = 'Error Loading';
    }
}

// Initialize the dashboard when the page loads
document.addEventListener('DOMContentLoaded', () => {
    window.dashboardApp = new DashboardApp();
    loadSettings();
    loadCurrentLogLevel();
    
    // Load account name after a short delay
    setTimeout(loadAccountName, 1000);
});

// Settings Modal Functions
function openSettingsModal() {
    document.getElementById('settingsModal').style.display = 'block';
    loadAccounts(); // Load accounts when opening settings
}

function closeSettingsModal() {
    document.getElementById('settingsModal').style.display = 'none';
}

// Settings Tab Switching Function
function switchSettingsTab(tabName) {
    // Remove active class from all tab buttons
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => button.classList.remove('active'));
    
    // Hide all tab content
    const tabContents = document.querySelectorAll('.tab-content');
    tabContents.forEach(content => content.classList.remove('active'));
    
    // Add active class to clicked tab button
    const activeButton = document.querySelector(`[data-tab="${tabName}"]`);
    if (activeButton) {
        activeButton.classList.add('active');
    }
    
    // Show corresponding tab content
    const activeContent = document.getElementById(`${tabName}-tab`);
    if (activeContent) {
        activeContent.classList.add('active');
        
        // Load duplicates when duplicates tab is opened
        if (tabName === 'duplicates') {
            loadDuplicates();
        }
    }
}

// Add Account Modal Functions
function openAddAccountModal() {
    document.getElementById('addAccountModal').style.display = 'block';
}

function closeAddAccountModal() {
    document.getElementById('addAccountModal').style.display = 'none';
    document.getElementById('addAccountForm').reset();
}

// Account Management Functions
async function loadAccounts() {
    try {
        const response = await fetch('/api/accounts');
        const data = await response.json();
        
        const selectors = [
            document.getElementById('accountSelector'),
            document.getElementById('viewAccountSelector')
        ].filter(el => el !== null);

        const activeInfos = [
            document.getElementById('activeAccountInfo'),
            document.getElementById('viewActiveAccountInfo')
        ].filter(el => el !== null);

        const removeBtns = [
            document.getElementById('removeAccountBtn'),
            document.getElementById('viewRemoveAccountBtn')
        ].filter(el => el !== null);
        
        // Clear existing options
        selectors.forEach(selector => selector.innerHTML = '');
        
        if (data.accounts && Object.keys(data.accounts).length > 0) {
            // Populate account selectors
            Object.entries(data.accounts).forEach(([id, account]) => {
                const option = document.createElement('option');
                option.value = id;
                option.textContent = `${account.name} (${id})`;
                if (id === data.active_account) {
                    option.selected = true;
                }
                selectors.forEach(selector => selector.appendChild(option.cloneNode(true)));
            });
            
            // Update active account info
            const activeAccount = data.accounts[data.active_account];
            if (activeAccount) {
                const lastUsed = new Date(activeAccount.last_used).toLocaleString();
                activeInfos.forEach(info => info.textContent = `${activeAccount.name} (${data.active_account}) - Last used: ${lastUsed}`);
            }
            
            // Enable/disable remove buttons based on account count
            removeBtns.forEach(btn => {
                btn.disabled = Object.keys(data.accounts).length <= 1;
                if (btn.disabled) {
                    btn.title = 'Cannot remove the only account';
                } else {
                    btn.title = '';
                }
            });
        } else {
            selectors.forEach(selector => selector.innerHTML = '<option value="">No accounts found</option>');
            activeInfos.forEach(info => info.textContent = 'No accounts configured');
            removeBtns.forEach(btn => btn.disabled = true);
        }
        
    } catch (error) {
        console.error('Error loading accounts:', error);
        const infos = [
            document.getElementById('activeAccountInfo'),
            document.getElementById('viewActiveAccountInfo')
        ].filter(el => el !== null);
        infos.forEach(info => info.textContent = 'Error loading accounts');
    }
}

async function switchAccount() {
    const selector = document.getElementById('accountSelector');
    if (selector) await performAccountSwitch(selector.value);
}

async function switchAccountView() {
    const selector = document.getElementById('viewAccountSelector');
    if (selector) await performAccountSwitch(selector.value);
}

async function performAccountSwitch(accountId) {
    if (!accountId) return;
    
    try {
        const response = await fetch('/api/accounts/switch', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ account_id: accountId })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast(
                'Account Switched Successfully!', 
                'main.py has been automatically restarted with the new account. The Discord client will reconnect shortly.', 
                'success', 
                6000
            );
            
            await loadAccounts();
            
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            showToast('Account Switch Failed', result.error || 'Failed to switch account', 'error');
        }
    } catch (error) {
        console.error('Error switching account:', error);
        showNotification('Error switching account', 'error');
    }
}

async function addAccount(event) {
    event.preventDefault();
    
    const formData = new FormData(event.target);
    const accountData = {
        name: formData.get('accountName'),
        discord_token: formData.get('discordToken'),
        webhook_urls: {
            friend: formData.get('webhookFriend'),
            message: formData.get('webhookMessage'),
            command: formData.get('webhookCommand')
        }
    };
    
    try {
        const response = await fetch('/api/accounts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(accountData)
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showNotification('Account added successfully!', 'success');
            closeAddAccountModal();
            await loadAccounts();
        } else {
            showNotification(result.error || 'Failed to add account', 'error');
        }
    } catch (error) {
        console.error('Error adding account:', error);
        showNotification('Error adding account', 'error');
    }
}

async function removeCurrentAccount() {
    const selector = document.getElementById('accountSelector');
    if (selector) await performAccountRemoval(selector);
}

async function removeCurrentAccountView() {
    const selector = document.getElementById('viewAccountSelector');
    if (selector) await performAccountRemoval(selector);
}

async function performAccountRemoval(selector) {
    const accountId = selector.value;
    if (!accountId) {
        showNotification('No account selected', 'error');
        return;
    }
    
    if (!confirm(`Are you sure you want to remove the account "${selector.options[selector.selectedIndex].text}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/accounts/${accountId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showNotification('Account removed successfully!', 'success');
            await loadAccounts();
            
            if (result.switched_account) {
                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            }
        } else {
            showNotification(result.error || 'Failed to remove account', 'error');
        }
    } catch (error) {
        console.error('Error removing account:', error);
        showNotification('Error removing account', 'error');
    }
}

function refreshAccounts() {
    loadAccounts();
}

// Notification system
// Toast Notification System
function showToast(title, message, type = 'info', duration = 5000) {
    const toastContainer = document.getElementById('toastContainer');
    const toastId = 'toast-' + Date.now();
    
    // Icon mapping for different toast types
    const icons = {
        'info': 'fas fa-info-circle',
        'success': 'fas fa-check-circle',
        'warning': 'fas fa-exclamation-triangle',
        'error': 'fas fa-times-circle'
    };
    
    // Create toast element
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-icon">
            <i class="${icons[type] || icons.info}"></i>
        </div>
        <div class="toast-content">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" onclick="removeToast('${toastId}')">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    // Add to container
    toastContainer.appendChild(toast);
    
    // Trigger show animation
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    // Auto remove after duration
    setTimeout(() => {
        removeToast(toastId);
    }, duration);
}

function removeToast(toastId) {
    const toast = document.getElementById(toastId);
    if (toast) {
        toast.classList.remove('show');
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }
}

// Legacy function for backward compatibility
function showNotification(message, type = 'info') {
    showToast('Notification', message, type);
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('settingsModal');
    if (event.target === modal) {
        closeSettingsModal();
    }
}

// Clear Interface Function
async function clearInterface() {
    if (confirm('Are you sure you want to clear all events and reset counters? This action cannot be undone.')) {
        try {
            const response = await fetch('/api/events/clear', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                // Reset all counters to 0
                document.getElementById('messagesCount').textContent = '0';
                document.getElementById('mentionsCount').textContent = '0';
                document.getElementById('deletionsCount').textContent = '0';
                document.getElementById('friendsCount').textContent = '0';
                
                // Clear the events list
                const eventsList = document.getElementById('eventsList');
                if (eventsList) {
                    eventsList.innerHTML = '<div class="no-events">No recent events</div>';
                }
                
                // Show success message
                alert('Interface cleared successfully!');
            } else {
                throw new Error('Failed to clear interface');
            }
        } catch (error) {
            console.error('Error clearing interface:', error);
            alert('Error clearing interface. Please try again.');
        }
    }
}

// Restart Web Server Function
async function restartWebServer() {
    if (confirm('Are you sure you want to restart the web server? This will temporarily disconnect all clients.')) {
        try {
            const response = await fetch('/api/server/restart', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                // Show success message
                showNotification('Server restart initiated. Page will reload automatically...', 'info');
                
                // Wait a moment then reload the page
                setTimeout(() => {
                    window.location.reload();
                }, 3000);
            } else {
                throw new Error('Failed to restart server');
            }
        } catch (error) {
            console.error('Error restarting server:', error);
            showNotification('Error restarting server. Please try again.', 'error');
        }
    }
}

// Webhook toggle functionality
let webhookEnabled = true;

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const settings = await response.json();
        webhookEnabled = settings.webhook_enabled !== false;
        updateWebhookToggle();
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

async function toggleWebhook() {
    webhookEnabled = !webhookEnabled;
    updateWebhookToggle();
    
    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                webhook_enabled: webhookEnabled
            })
        });
    } catch (error) {
        console.error('Error updating webhook setting:', error);
        // Revert on error
        webhookEnabled = !webhookEnabled;
        updateWebhookToggle();
    }
}

function updateWebhookToggle() {
    const toggles = [
        document.getElementById('webhookToggle'),
        document.getElementById('viewWebhookToggle')
    ].filter(el => el !== null);
    
    toggles.forEach(toggle => {
        if (webhookEnabled) {
            toggle.classList.add('active');
        } else {
            toggle.classList.remove('active');
        }
    });
}

async function changeLogLevel() {
    const select = document.getElementById('logLevelSelect');
    if (select) await performLogLevelChange(select.value);
}

async function changeLogLevelView() {
    const select = document.getElementById('viewLogLevelSelect');
    if (select) await performLogLevelChange(select.value);
}

async function performLogLevelChange(newLogLevel) {
    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                log_level: newLogLevel
            })
        });
        
        if (response.ok) {
            showNotification('Logging level updated successfully', 'success');
            // Update both selects
            const selects = [
                document.getElementById('logLevelSelect'),
                document.getElementById('viewLogLevelSelect')
            ].filter(el => el !== null);
            selects.forEach(s => s.value = newLogLevel);
        } else {
            throw new Error('Failed to update logging level');
        }
    } catch (error) {
        console.error('Error updating logging level:', error);
        showNotification('Failed to update logging level', 'error');
        await loadCurrentLogLevel();
    }
}

async function loadCurrentLogLevel() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        const selects = [
            document.getElementById('logLevelSelect'),
            document.getElementById('viewLogLevelSelect')
        ].filter(el => el !== null);
        
        if (config.log_level) {
            selects.forEach(s => s.value = config.log_level);
        }
    } catch (error) {
        console.error('Error loading current log level:', error);
    }
}

// Layout & Theme Management Functions
function setTheme(themeName) {
    if (window.dashboardApp) window.dashboardApp.setTheme(themeName);
}

function setLayout(layoutName) {
    if (window.dashboardApp) window.dashboardApp.setLayout(layoutName);
}

// Context Menu Functionality
let contextMenuData = {
    channelId: null,
    channelName: null,
    author: null,
    eventElement: null
};

// Store user preferences
let userPreferences = {
    taggedChannels: new Set(),
    favoriteUsers: new Set(),
    autoDownloadUsers: new Set()
};

// Load preferences from backend and localStorage
async function loadUserPreferences() {
    try {
        // First try to load from backend
        const response = await fetch('/api/preferences');
        if (response.ok) {
            const backendPrefs = await response.json();
            userPreferences.taggedChannels = new Set(backendPrefs.tagged_channels || []);
            userPreferences.favoriteUsers = new Set(backendPrefs.favorite_users || []);
            userPreferences.autoDownloadUsers = new Set(backendPrefs.auto_download_users || []);
            
            // Save to localStorage as backup
            saveUserPreferences();
            return;
        }
    } catch (error) {
        console.warn('Could not load preferences from backend, trying localStorage:', error);
    }
    
    // Fallback to localStorage
    try {
        const saved = localStorage.getItem('userPreferences');
        if (saved) {
            const parsed = JSON.parse(saved);
            userPreferences.taggedChannels = new Set(parsed.taggedChannels || []);
            userPreferences.favoriteUsers = new Set(parsed.favoriteUsers || []);
            userPreferences.autoDownloadUsers = new Set(parsed.autoDownloadUsers || []);
        }
    } catch (error) {
        console.error('Error loading user preferences from localStorage:', error);
    }
}

// Save preferences to localStorage
function saveUserPreferences() {
    try {
        const toSave = {
            taggedChannels: Array.from(userPreferences.taggedChannels),
            favoriteUsers: Array.from(userPreferences.favoriteUsers),
            autoDownloadUsers: Array.from(userPreferences.autoDownloadUsers)
        };
        localStorage.setItem('userPreferences', JSON.stringify(toSave));
    } catch (error) {
        console.error('Error saving user preferences:', error);
    }
}

// Show context menu
function showContextMenu(event, eventData) {
    event.preventDefault();
    
    const contextMenu = document.getElementById('contextMenu');
    const tagBtn = document.getElementById('tagChannelBtn');
    const untagBtn = document.getElementById('untagChannelBtn');
    const favoriteBtn = document.getElementById('favoriteUserBtn');
    const unfavoriteBtn = document.getElementById('unfavoriteUserBtn');
    const autoDownloadBtn = document.getElementById('autoDownloadBtn');
    const disableAutoDownloadBtn = document.getElementById('disableAutoDownloadBtn');
    
    // Store context data
    contextMenuData = {
        channelId: eventData.channel_id,
        channelName: eventData.channel_name,
        author: eventData.author,
        eventElement: event.currentTarget
    };
    
    // Update button visibility based on current state
    const isTagged = userPreferences.taggedChannels.has(eventData.channel_id);
    const isFavorite = userPreferences.favoriteUsers.has(eventData.author);
    const isAutoDownload = userPreferences.autoDownloadUsers.has(eventData.author);
    
    tagBtn.style.display = isTagged ? 'none' : 'flex';
    untagBtn.style.display = isTagged ? 'flex' : 'none';
    favoriteBtn.style.display = isFavorite ? 'none' : 'flex';
    unfavoriteBtn.style.display = isFavorite ? 'flex' : 'none';
    autoDownloadBtn.style.display = isAutoDownload ? 'none' : 'flex';
    disableAutoDownloadBtn.style.display = isAutoDownload ? 'flex' : 'none';
    
    // Position context menu
    contextMenu.style.left = event.pageX + 'px';
    contextMenu.style.top = event.pageY + 'px';
    contextMenu.style.display = 'block';
    
    // Adjust position if menu goes off screen
    const rect = contextMenu.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
        contextMenu.style.left = (event.pageX - rect.width) + 'px';
    }
    if (rect.bottom > window.innerHeight) {
        contextMenu.style.top = (event.pageY - rect.height) + 'px';
    }
}

// Hide context menu
function hideContextMenu() {
    document.getElementById('contextMenu').style.display = 'none';
}

// Tag/Untag channel
async function toggleChannelTag() {
    const { channelId, channelName } = contextMenuData;
    const isTagged = userPreferences.taggedChannels.has(channelId);
    const action = isTagged ? 'untag' : 'tag';
    
    try {
        const response = await fetch('/api/preferences/channel/tag', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                channel_id: channelId,
                channel_name: channelName,
                action: action
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (action === 'tag') {
                userPreferences.taggedChannels.add(channelId);
                showNotification(`Tagged ${channelName} as group chat`, 'success');
            } else {
                userPreferences.taggedChannels.delete(channelId);
                showNotification(`Removed group tag from ${channelName}`, 'info');
            }
            
            saveUserPreferences();
            updateEventDisplays();
        } else {
            showNotification('Failed to update channel tag', 'error');
        }
    } catch (error) {
        console.error('Error toggling channel tag:', error);
        showNotification('Error updating channel tag', 'error');
    }
    
    hideContextMenu();
}

// Favorite/Unfavorite user
async function toggleUserFavorite() {
    const { author } = contextMenuData;
    const isFavorite = userPreferences.favoriteUsers.has(author);
    const action = isFavorite ? 'unfavorite' : 'favorite';
    
    try {
        const response = await fetch('/api/preferences/user/favorite', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                username: author,
                action: action
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (action === 'favorite') {
                userPreferences.favoriteUsers.add(author);
                showNotification(`Added ${author} to favorites`, 'success');
            } else {
                userPreferences.favoriteUsers.delete(author);
                showNotification(`Removed ${author} from favorites`, 'info');
            }
            
            saveUserPreferences();
            updateEventDisplays();
        } else {
            showNotification('Failed to update user favorite', 'error');
        }
    } catch (error) {
        console.error('Error toggling user favorite:', error);
        showNotification('Error updating user favorite', 'error');
    }
    
    hideContextMenu();
}

// Toggle auto-download
async function toggleAutoDownload() {
    const { author } = contextMenuData;
    const isAutoDownload = userPreferences.autoDownloadUsers.has(author);
    const action = isAutoDownload ? 'disable' : 'enable';
    
    try {
        const response = await fetch('/api/preferences/user/autodownload', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                username: author,
                action: action
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (action === 'enable') {
                userPreferences.autoDownloadUsers.add(author);
                showNotification(`Enabled auto-download for ${author}`, 'success');
            } else {
                userPreferences.autoDownloadUsers.delete(author);
                showNotification(`Disabled auto-download for ${author}`, 'info');
            }
            
            saveUserPreferences();
            updateEventDisplays();
        } else {
            showNotification('Failed to update auto-download setting', 'error');
        }
    } catch (error) {
        console.error('Error toggling auto-download:', error);
        showNotification('Error updating auto-download setting', 'error');
    }
    
    hideContextMenu();
}

// Update event displays with indicators
function updateEventDisplays() {
    document.querySelectorAll('.event-item').forEach(eventElement => {
        const eventData = eventElement._eventData;
        if (!eventData) return;
        
        // Remove existing indicators
        eventElement.querySelectorAll('.channel-tag, .favorite-user, .auto-download').forEach(el => el.remove());
        
        const descriptionElement = eventElement.querySelector('.event-description');
        if (!descriptionElement) return;
        
        // Add channel tag indicator
        if (eventData.channel_id && userPreferences.taggedChannels.has(eventData.channel_id)) {
            const tag = document.createElement('span');
            tag.className = 'channel-tag';
            tag.innerHTML = '<i class="fas fa-users"></i> Group';
            descriptionElement.appendChild(tag);
        }
        
        // Add favorite user indicator
        if (eventData.author && userPreferences.favoriteUsers.has(eventData.author)) {
            const star = document.createElement('i');
            star.className = 'fas fa-star favorite-user';
            star.title = 'Favorite User';
            descriptionElement.appendChild(star);
        }
        
        // Add auto-download indicator
        if (eventData.author && userPreferences.autoDownloadUsers.has(eventData.author)) {
            const download = document.createElement('i');
            download.className = 'fas fa-download auto-download';
            download.title = 'Auto-download Enabled';
            descriptionElement.appendChild(download);
        }
    });
}

// Initialize context menu event listeners
function initializeContextMenu() {
    // Context menu button handlers
    document.getElementById('tagChannelBtn').addEventListener('click', toggleChannelTag);
    document.getElementById('untagChannelBtn').addEventListener('click', toggleChannelTag);
    document.getElementById('favoriteUserBtn').addEventListener('click', toggleUserFavorite);
    document.getElementById('unfavoriteUserBtn').addEventListener('click', toggleUserFavorite);
    document.getElementById('autoDownloadBtn').addEventListener('click', toggleAutoDownload);
    document.getElementById('disableAutoDownloadBtn').addEventListener('click', toggleAutoDownload);
    
    // Hide context menu when clicking elsewhere
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#contextMenu')) {
            hideContextMenu();
        }
    });
    
    // Hide context menu on scroll
    document.addEventListener('scroll', hideContextMenu);
}

// Duplicates Management Functions
async function loadDuplicates() {
    try {
        const response = await fetch('/api/duplicates');
        const data = await response.json();
        renderDuplicates(data.duplicates || []);
    } catch (error) {
        console.error('Error loading duplicates:', error);
        document.getElementById('duplicatesList').innerHTML = '<div class="no-duplicates">Error loading duplicates</div>';
    }
}

function renderDuplicates(duplicates) {
    const containers = [
        document.getElementById('duplicatesList'),
        document.getElementById('viewDuplicatesList')
    ].filter(el => el !== null);
    
    if (containers.length === 0) return;
    
    if (duplicates.length === 0) {
        containers.forEach(c => c.innerHTML = '<div class="no-duplicates">No duplicate messages found</div>');
        return;
    }

    const html = duplicates.map(duplicate => `
        <div class="duplicate-item" data-id="${duplicate.id}">
            <div class="duplicate-header">
                <div class="duplicate-info">
                    <div class="duplicate-channel">#${duplicate.channel_name || 'Unknown Channel'}</div>
                    <div class="duplicate-time">${new Date(duplicate.timestamp).toLocaleString()}</div>
                </div>
                <div class="duplicate-actions">
                    <button class="btn btn-sm btn-danger" onclick="removeDuplicate('${duplicate.id}')">
                        <i class="fas fa-times"></i> Remove
                    </button>
                </div>
            </div>
            <div class="duplicate-content">${duplicate.content}</div>
            <div class="duplicate-metadata">
                <small>Author: ${duplicate.author} | Similarity: ${Math.round(duplicate.similarity * 100)}%</small>
            </div>
        </div>
    `).join('');

    containers.forEach(c => c.innerHTML = html);
}

async function removeDuplicate(duplicateId) {
    try {
        const response = await fetch(`/api/duplicates/${duplicateId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            // Remove the duplicate item from the UI in all containers
            const duplicateElements = document.querySelectorAll(`[data-id="${duplicateId}"]`);
            duplicateElements.forEach(el => el.remove());
            
            // Check if lists are now empty
            const containers = [
                document.getElementById('duplicatesList'),
                document.getElementById('viewDuplicatesList')
            ].filter(el => el !== null);

            containers.forEach(container => {
                if (container.children.length === 0) {
                    container.innerHTML = '<div class="no-duplicates">No duplicate messages found</div>';
                }
            });
            
            showNotification('Duplicate removed successfully', 'success');
        } else {
            showNotification('Failed to remove duplicate', 'error');
        }
    } catch (error) {
        console.error('Error removing duplicate:', error);
        showNotification('Error removing duplicate', 'error');
    }
}

async function clearAllDuplicates() {
    if (!confirm('Are you sure you want to clear all flagged duplicates? This action cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch('/api/duplicates/clear', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            const containers = [
                document.getElementById('duplicatesList'),
                document.getElementById('viewDuplicatesList')
            ].filter(el => el !== null);
            
            containers.forEach(c => c.innerHTML = '<div class="no-duplicates">No duplicate messages found</div>');
            showNotification('All duplicates cleared successfully', 'success');
        } else {
            showNotification('Failed to clear duplicates', 'error');
        }
    } catch (error) {
        console.error('Error clearing duplicates:', error);
        showNotification('Error clearing duplicates', 'error');
    }
}

// Initialize theme on page load
document.addEventListener('DOMContentLoaded', async function() {
    loadSavedTheme();
    await loadUserPreferences();
    initializeContextMenu();
});

