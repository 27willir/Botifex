/**
 * WebSocket Client for Real-Time Notifications
 * Handles real-time updates for listings, alerts, and system status
 */

class SuperBotWebSocket {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.listeners = {};

        this._token = null;
        this._tokenExpiry = 0;
        this._tokenRefreshTimer = null;

        this._isConnecting = false;
        this._manualDisconnect = false;
        this._reconnectDelay = 2000;
        this._maxReconnectDelay = 20000;
        this._reconnectTimer = null;
        this._libraryPromise = null;
    }

    /**
     * Public: establish a websocket connection (with auto-retry)
     */
    async connect() {
        if (this.connected || this._isConnecting) {
            return;
        }

        this._isConnecting = true;
        this._manualDisconnect = false;

        try {
            await this._ensureSocketLibrary();
            await this._initializeSocket();
        } catch (error) {
            console.error('WebSocket connection error:', error);
            this._scheduleReconnect();
        } finally {
            this._isConnecting = false;
        }
    }

    /**
     * Gracefully close the websocket connection and stop retries
     */
    disconnect() {
        this._manualDisconnect = true;
        this._clearReconnectTimer();
        this._clearTokenRefreshTimer();

        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }
        this.connected = false;
    }

    /**
     * Subscribe to websocket events
     */
    on(event, callback) {
        if (!this.listeners[event]) {
            this.listeners[event] = [];
        }
        this.listeners[event].push(callback);
    }

    /**
     * Unsubscribe from websocket events
     */
    off(event, callback) {
        if (!this.listeners[event]) {
            return;
        }
        this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    }

    /**
     * Emit custom events to registered listeners
     */
    trigger(event, payload) {
        (this.listeners[event] || []).forEach(callback => {
            try {
                callback(payload);
            } catch (error) {
                console.error(`WebSocket listener for '${event}' failed`, error);
            }
        });
    }

    /**
     * Subscribe to scraper status updates
     */
    subscribeScraperStatus() {
        if (this.socket) {
            this.socket.emit('subscribe_scraper_status');
        }
    }

    /**
     * Unsubscribe from scraper status updates
     */
    unsubscribeScraperStatus() {
        if (this.socket) {
            this.socket.emit('unsubscribe_scraper_status');
        }
    }

    /**
     * Send ping to check connection
     */
    ping() {
        if (this.socket) {
            this.socket.emit('ping');
        }
    }

    // ---------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------

    async _ensureSocketLibrary() {
        if (typeof io !== 'undefined') {
            return;
        }

        if (!this._libraryPromise) {
            this._libraryPromise = this._loadSocketIoLibrary().finally(() => {
                this._libraryPromise = null;
            });
        }

        await this._libraryPromise;

        if (typeof io === 'undefined') {
            throw new Error('Socket.IO library unavailable');
        }
    }

    async _loadSocketIoLibrary() {
        const sources = [
            'https://cdn.socket.io/4.5.4/socket.io.min.js',
            '/socket.io/socket.io.js'
        ];
        let lastError = null;
        for (const src of sources) {
            try {
                await this._loadScript(src);
                if (typeof io !== 'undefined') {
                    return;
                }
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError || new Error('Unable to load Socket.IO library');
    }

    _loadScript(src) {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[src="${src}"]`);
            if (existing) {
                if (existing.getAttribute('data-socket-loaded') === '1') {
                    resolve();
                    return;
                }
                const onExistingLoad = () => {
                    existing.setAttribute('data-socket-loaded', '1');
                    existing.removeEventListener('load', onExistingLoad);
                    existing.removeEventListener('error', onExistingError);
                    resolve();
                };
                const onExistingError = () => {
                    existing.removeEventListener('load', onExistingLoad);
                    existing.removeEventListener('error', onExistingError);
                    reject(new Error(`Failed to load Socket.IO library from ${src}`));
                };
                existing.addEventListener('load', onExistingLoad);
                existing.addEventListener('error', onExistingError);
                return;
            }

            const script = document.createElement('script');
            script.src = src;
            script.async = true;

            const cleanup = () => {
                script.removeEventListener('load', onLoad);
                script.removeEventListener('error', onError);
            };

            const onLoad = () => {
                script.setAttribute('data-socket-loaded', '1');
                cleanup();
                resolve();
            };

            const onError = () => {
                cleanup();
                script.remove();
                reject(new Error(`Failed to load Socket.IO library from ${src}`));
            };

            script.addEventListener('load', onLoad);
            script.addEventListener('error', onError);
            document.head.appendChild(script);
        });
    }

    async _initializeSocket() {
        const tokenData = await this._fetchRealtimeToken().catch(() => null);
        const options = tokenData?.token ? { query: { token: tokenData.token } } : {};

        this.socket = io('/', options);
        this._registerSocketHandlers();
    }

    _registerSocketHandlers() {
        if (!this.socket) {
            return;
        }

        this.socket.on('connect', () => {
            this.connected = true;
            this._clearReconnectTimer();
            this._reconnectDelay = 2000;
            this.trigger('connected');
            this.trigger('status', { status: 'connected', timestamp: new Date().toISOString() });
        });

        this.socket.on('disconnect', (reason) => {
            this.connected = false;
            this.trigger('disconnected', { reason });
            this.trigger('status', { status: 'disconnected', reason });

            if (!this._manualDisconnect) {
                this._scheduleReconnect();
            }
        });

        this.socket.on('reconnect_attempt', () => {
            this.trigger('status', { status: 'connecting' });
        });

        this.socket.on('connect_error', (error) => {
            this.trigger('status', { status: 'error', error: error?.message });
        });

        this.socket.on('connection_status', (data) => {
            this.trigger('status', data);
        });

        // Business events --------------------------------------------------
        this.socket.on('new_listing', (data) => {
            this.trigger('new_listing', data);
            this._maybeNotify('New Listing!', `${data.title} - $${data.price}`, data.link);
        });

        this.socket.on('notification', (data) => {
            this.trigger('notification', data);
            this._handleNotification(data);
        });

        this.socket.on('scraper_status_update', (data) => {
            this.trigger('scraper_status', data);
        });

        this.socket.on('channel.presence', (data) => {
            this.trigger('channel.presence', data);
        });

        this.socket.on('channel.typing', (data) => {
            this.trigger('channel.typing', data);
        });

        this.socket.on('system_message', (data) => {
            this.trigger('system_message', data);
            this._showSystemMessage(data.message, data.level);
        });

        this.socket.on('pong', (data) => {
            this.trigger('pong', data);
        });
    }

    _scheduleReconnect() {
        if (this._manualDisconnect || this.connected) {
            return;
        }
        if (this._reconnectTimer) {
            return;
        }

        this.trigger('status', { status: 'connecting' });

        this._reconnectTimer = setTimeout(() => {
            this._reconnectTimer = null;
            this.connect();
            this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, this._maxReconnectDelay);
        }, this._reconnectDelay);
    }

    _clearReconnectTimer() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
    }

    async _fetchRealtimeToken() {
        try {
            const response = await fetch('/api/realtime/token', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Accept': 'application/json',
                },
            });

            if (!response.ok) {
                return null;
            }

            const data = await response.json();
            if (!data.token) {
                return null;
            }

            this._token = data.token;
            const ttlSeconds = Number(data.expires_in || 0);
            this._tokenExpiry = Date.now() + ttlSeconds * 1000;
            this._scheduleTokenRefresh(Math.max(ttlSeconds - 30, 10));
            return data;
        } catch (error) {
            console.debug('Realtime token fetch failed:', error);
            return null;
        }
    }

    _scheduleTokenRefresh(seconds) {
        this._clearTokenRefreshTimer();
        if (seconds <= 0) {
            return;
        }
        this._tokenRefreshTimer = setTimeout(() => this._refreshToken(), seconds * 1000);
    }

    _clearTokenRefreshTimer() {
        if (this._tokenRefreshTimer) {
            clearTimeout(this._tokenRefreshTimer);
            this._tokenRefreshTimer = null;
        }
    }

    async _refreshToken() {
        const tokenData = await this._fetchRealtimeToken();
        if (!tokenData || !this.socket) {
            return;
        }

        if (!this.socket.io || !this.socket.io.opts) {
            return;
        }

        this.socket.io.opts.query = this.socket.io.opts.query || {};
        this.socket.io.opts.query.token = tokenData.token;

        // Force a reconnect if the socket is currently disconnected
        if (!this.connected && !this._isConnecting) {
            this.connect();
        }
    }

    _maybeNotify(title, body, link = null) {
        if (!('Notification' in window)) {
            return;
        }

        const show = () => {
            const options = {
                body,
                icon: '/static/img/logo.png',
                badge: '/static/img/badge.png',
                tag: 'superbot-notification',
                requireInteraction: false,
            };

            const notification = new Notification(title, options);
            if (link) {
                notification.onclick = () => {
                    window.open(link, '_blank');
                    notification.close();
                };
            }
            setTimeout(() => notification.close(), 10000);
        };

        if (Notification.permission === 'granted') {
            show();
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission().then((permission) => {
                if (permission === 'granted') {
                    show();
                }
            });
        }
    }

    _handleNotification(payload) {
        const message = payload?.data?.message || 'New update';
        switch (payload?.type) {
            case 'price_alert':
                this._maybeNotify('🚨 Price Alert!', message, payload?.data?.listing);
                break;
            case 'saved_search':
                this._maybeNotify('💾 Saved Search Results', message);
                break;
            default:
                this._maybeNotify('Notification', message);
        }
    }

    _showSystemMessage(message, level = 'info') {
        const alertClass = {
            info: 'alert-info',
            success: 'alert-success',
            warning: 'alert-warning',
            error: 'alert-danger',
        }[level] || 'alert-info';

        const alert = document.createElement('div');
        alert.className = `alert ${alertClass} alert-dismissible fade show`;
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        let container = document.querySelector('.alerts-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'alerts-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '9999';
            document.body.appendChild(container);
        }

        container.appendChild(alert);
        setTimeout(() => alert.remove(), 5000);
    }
}

// Create global instance
const wsClient = new SuperBotWebSocket();

// Auto-connect when page loads
window.addEventListener('DOMContentLoaded', () => {
    wsClient.connect();

    if (window.location.pathname === '/' || window.location.pathname === '/index') {
        wsClient.subscribeScraperStatus();
    }
});


