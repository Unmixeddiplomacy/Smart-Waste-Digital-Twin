/**
 * WebSocket Client for Smart Waste Sorting Digital Twin
 * Auto-reconnects on disconnect. Dispatches messages by type to registered handlers.
 */
class WSClient {
  constructor() {
    this.ws = null;
    this.url = `ws://${window.location.host}/ws`;
    this.reconnectInterval = 3000;
    this.handlers = {};
    this._reconnectTimer = null;
    this._disconnectedAlerted = false;
    this.connect();
  }

  connect() {
    // Clear any pending reconnect timer to prevent stacking
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }

    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this._disconnectedAlerted = false;
      const el = document.getElementById('connection-status');
      if (el) {
        el.textContent = '● Connected';
        el.style.color = '#00ff88';
        el.classList.add('connected');
      }
      if (this.handlers['connect']) {
        this.handlers['connect']();
      }
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected, reconnecting...');
      const el = document.getElementById('connection-status');
      if (el) {
        el.textContent = '● Disconnected';
        el.style.color = '#ff4444';
        el.classList.remove('connected');
      }
      if (!this._disconnectedAlerted) {
        this._disconnectedAlerted = true;
        if (this.handlers['close']) {
          this.handlers['close']();
        }
      }
      // Schedule reconnect (only if no timer already pending)
      if (!this._reconnectTimer) {
        this._reconnectTimer = setTimeout(() => {
          this._reconnectTimer = null;
          this.connect();
        }, this.reconnectInterval);
      }
    };

    this.ws.onerror = (err) => {
      console.error('WebSocket error', err);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type && this.handlers[msg.type]) {
          this.handlers[msg.type](msg.data);
        } else {
          console.log('Unhandled message:', msg);
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };
  }

  /**
   * Register a handler for a specific message type.
   * @param {string} eventType - The message type to handle (e.g. 'sort_event', 'stats_update')
   * @param {function} callback - Function called with msg.data when type matches
   */
  on(eventType, callback) {
    this.handlers[eventType] = callback;
  }

  /**
   * Send a JSON message to the server.
   * @param {object} message - Object to JSON-stringify and send
   */
  send(message) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }
}

// Global instance — available to twin3d.js and dashboard.js
const wsClient = new WSClient();
