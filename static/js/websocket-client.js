/**
 * WebSocket Client for Real-Time Notifications
 * Handles real-time updates for listings, alerts, and system status
 */

class SuperBotWebSocket {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.listeners = {};
    }

    /**
     * Initialize WebSocket connection
     */
    connect() {
        // Load Socket.IO from CDN if not already loaded
        if (typeof io === 'undefined') {
            const script = document.createElement('script');
            script.src = 'https://cdn.socket.io/4.5.4/socket.io.min.js';
            script.onload = () => this.initSocket();
            document.head.appendChild(script);
        } else {
            this.initSocket();
        }
    }

    /**
     * Initialize socket connection
     */
    initSocket() {
        this.socket = io();
        
        // Connection event handlers
        this.socket.on('connect', () => {
            console.log('✅ WebSocket connected');
            this.connected = true;
            this.trigger('connected');
        });

        this.socket.on('disconnect', () => {
            console.log('❌ WebSocket disconnected');
            this.connected = false;
            this.trigger('disconnected');
        });

        this.socket.on('connection_status', (data) => {
            console.log('Connection status:', data);
            this.trigger('status', data);
        });

        // Listing notifications
        this.socket.on('new_listing', (data) => {
            console.log('📢 New listing:', data);
            this.trigger('new_listing', data);
            this.showNotification('New Listing!', `${data.title} - $${data.price}`);
        });

        // User notifications
        this.socket.on('notification', (data) => {
            console.log('🔔 Notification:', data);
            this.trigger('notification', data);
            this.handleNotification(data);
        });

        // Scraper status updates
        this.socket.on('scraper_status_update', (data) => {
            console.log('🤖 Scraper status update:', data);
            this.trigger('scraper_status', data);
        });

        // System messages
        this.socket.on('system_message', (data) => {
            console.log('📨 System message:', data);
            this.trigger('system_message', data);
            this.showSystemMessage(data.message, data.level);
        });

        // Ping/pong for health check
        this.socket.on('pong', (data) => {
            console.log('🏓 Pong received:', data);
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

    /**
     * Add event listener
     */
    on(event, callback) {
        if (!this.listeners[event]) {
            this.listeners[event] = [];
        }
        this.listeners[event].push(callback);
    }

    /**
     * Trigger event listeners
     */
    trigger(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(callback => callback(data));
        }
    }

    /**
     * Handle incoming notification
     */
    handleNotification(data) {
        switch (data.type) {
            case 'price_alert':
                this.showNotification(
                    '🚨 Price Alert!',
                    data.data.message,
                    data.data.listing
                );
                break;
            
            case 'saved_search':
                this.showNotification(
                    '💾 Saved Search Results',
                    data.data.message
                );
                break;
            
            default:
                this.showNotification('Notification', data.data.message || 'New update');
        }
    }

    /**
     * Show browser notification
     */
    showNotification(title, body, link = null) {
        // Check if browser supports notifications
        if (!('Notification' in window)) {
            console.log('Browser does not support notifications');
            return;
        }

        // Request permission if needed
        if (Notification.permission === 'granted') {
            this.createNotification(title, body, link);
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    this.createNotification(title, body, link);
                }
            });
        }
    }

    /**
     * Create browser notification
     */
    createNotification(title, body, link = null) {
        const notification = new Notification(title, {
            body: body,
            icon: '/static/img/logo.png',
            badge: '/static/img/badge.png',
            tag: 'superbot-notification',
            requireInteraction: false
        });

        if (link) {
            notification.onclick = () => {
                window.open(link, '_blank');
                notification.close();
            };
        }

        // Auto-close after 10 seconds
        setTimeout(() => notification.close(), 10000);
    }

    /**
     * Show in-page system message
     */
    showSystemMessage(message, level = 'info') {
        // Try to show as a flash message in the UI
        const alertClass = {
            'info': 'alert-info',
            'success': 'alert-success',
            'warning': 'alert-warning',
            'error': 'alert-danger'
        }[level] || 'alert-info';

        const alert = document.createElement('div');
        alert.className = `alert ${alertClass} alert-dismissible fade show`;
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        // Find alerts container or create one
        let container = document.querySelector('.alerts-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'alerts-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '9999';
            document.body.appendChild(container);
        }

        container.appendChild(alert);

        // Auto-dismiss after 5 seconds
        setTimeout(() => alert.remove(), 5000);
    }

    /**
     * Disconnect WebSocket
     */
    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.connected = false;
        }
    }
}

// Create global instance
const wsClient = new SuperBotWebSocket();

// Auto-connect when page loads
document.addEventListener('DOMContentLoaded', () => {
    wsClient.connect();
    
    // Subscribe to scraper status on dashboard page
    if (window.location.pathname === '/' || window.location.pathname === '/index') {
        wsClient.subscribeScraperStatus();
    }
});

// Example usage:
// wsClient.on('new_listing', (data) => {
//     console.log('New listing received:', data);
//     // Update UI with new listing
// });

// wsClient.on('scraper_status', (data) => {
//     console.log('Scraper status changed:', data);
//     // Update status indicators
// });

