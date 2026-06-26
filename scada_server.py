#!/usr/bin/env python3
"""
Railroad North - Central SCADA Server
Operator interface for railroad control
"""

import json
import logging
import os
from datetime import datetime
from enum import Enum
from typing import Dict, List
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS
import requests

logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATA STRUCTURES
# ============================================================================

class RouteOption(Enum):
    ROUTE_A = 1  # Express
    ROUTE_B = 2  # Local
    ROUTE_C = 3  # Maintenance

# ============================================================================
# SCADA SERVER CLASS
# ============================================================================

class SCADAServer:
    """Central SCADA server for railroad control"""
    
    def __init__(self):
        self.master_plc_ip = os.environ.get('MASTER_PLC_IP', '172.25.0.10')
        self.master_plc_port = int(os.environ.get('MASTER_PLC_PORT', 502))
        
        # Segment configuration
        self.segments = {
            1: {'name': 'North (Entrance)', 'ip': '172.25.1.10'},
            2: {'name': 'Central (Junction)', 'ip': '172.25.2.10'},
            3: {'name': 'South (Yard)', 'ip': '172.25.3.10'}
        }
        
        # Command history
        self.command_history: List[Dict] = []
        
        logger.info("SCADA Server initialized")
    
    def get_master_status(self) -> Dict:
        """Get master PLC status"""
        try:
            response = requests.get(
                f'http://{self.master_plc_ip}:8080/api/status',
                timeout=2
            )
            return response.json()
        except Exception as e:
            logger.error(f"Cannot reach Master PLC: {e}")
            return {'error': 'Master PLC unreachable'}
    
    def send_route_command(self, segment_id: int, route: str) -> Dict:
        """Send route change command to master PLC"""
        try:
            command_data = {
                'segment_id': segment_id,
                'route': route,
                'timestamp': datetime.now().isoformat(),
                'operator': 'SCADA'
            }
            
            response = requests.post(
                f'http://{self.master_plc_ip}:8080/api/command',
                json=command_data,
                timeout=2
            )
            
            result = response.json()
            
            # Log command
            self.command_history.append({
                **command_data,
                'result': result
            })
            
            logger.info(f"Command sent: Segment {segment_id} -> Route {route}")
            
            return result
        except Exception as e:
            logger.error(f"Command failed: {e}")
            return {'error': str(e), 'success': False}
    
    def get_system_overview(self) -> Dict:
        """Get complete system overview"""
        master_status = self.get_master_status()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'master_plc': master_status,
            'segments': self.segments,
            'recent_commands': self.command_history[-5:]
        }

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__)
CORS(app)
scada = SCADAServer()

# ============================================================================
# WEB INTERFACE
# ============================================================================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Railroad North - SCADA Control Center</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            color: #00ff00;
            padding: 20px;
            min-height: 100vh;
        }
        .header {
            background: #000;
            border: 2px solid #00ff00;
            padding: 20px;
            margin-bottom: 20px;
            text-align: center;
        }
        .header h1 {
            font-size: 28px;
            letter-spacing: 2px;
            margin-bottom: 5px;
        }
        .status-bar {
            background: #111;
            border: 1px solid #00ff00;
            padding: 10px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
        }
        .container {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
        }
        .segment {
            background: #1a1a1a;
            border: 2px solid #00ff00;
            padding: 20px;
            border-radius: 5px;
        }
        .segment h3 {
            margin-bottom: 15px;
            color: #ffff00;
        }
        .segment-status {
            background: #0a0a0a;
            padding: 10px;
            margin-bottom: 10px;
            border-left: 3px solid #00ff00;
        }
        .control-buttons {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
        }
        button {
            background: #1a1a1a;
            color: #00ff00;
            border: 1px solid #00ff00;
            padding: 8px 15px;
            cursor: pointer;
            font-family: monospace;
            font-size: 12px;
            transition: all 0.3s;
        }
        button:hover {
            background: #00ff00;
            color: #000;
        }
        button:active {
            transform: scale(0.95);
        }
        .log-panel {
            grid-column: 1 / -1;
            background: #0a0a0a;
            border: 2px solid #00ff00;
            padding: 20px;
            max-height: 300px;
            overflow-y: auto;
            font-size: 12px;
        }
        .log-entry {
            margin: 5px 0;
            padding: 5px;
            border-left: 2px solid #00ff00;
            padding-left: 10px;
        }
        .success { color: #00ff00; }
        .error { color: #ff0000; }
        .warning { color: #ffff00; }
        .info { color: #00ffff; }
    </style>
</head>
<body>
    <div class="header">
        <h1>RAILROAD NORTH</h1>
        <p>Central SCADA Control Center - Master-Slave PLC Architecture</p>
    </div>
    
    <div class="status-bar">
        <span>Master PLC: <span id="master-status">Connecting...</span></span>
        <span>System Time: <span id="system-time">--:--:--</span></span>
        <span>Total Commands: <span id="command-count">0</span></span>
    </div>
    
    <div class="container">
        <div class="segment">
            <h3>🚂 Segment 1: North (Entrance)</h3>
            <div class="segment-status">
                <div id="seg1-status">Loading...</div>
            </div>
            <div class="control-buttons">
                <button onclick="sendCommand(1, 'ROUTE_A')">Route A (Express)</button>
                <button onclick="sendCommand(1, 'ROUTE_B')">Route B (Local)</button>
                <button onclick="sendCommand(1, 'ROUTE_C')">Route C (Maint)</button>
            </div>
        </div>
        
        <div class="segment">
            <h3>🚄 Segment 2: Central (Junction)</h3>
            <div class="segment-status">
                <div id="seg2-status">Loading...</div>
            </div>
            <div class="control-buttons">
                <button onclick="sendCommand(2, 'ROUTE_A')">Route A (Express)</button>
                <button onclick="sendCommand(2, 'ROUTE_B')">Route B (Local)</button>
                <button onclick="sendCommand(2, 'ROUTE_C')">Route C (Maint)</button>
            </div>
        </div>
        
        <div class="segment">
            <h3>🚃 Segment 3: South (Yard)</h3>
            <div class="segment-status">
                <div id="seg3-status">Loading...</div>
            </div>
            <div class="control-buttons">
                <button onclick="sendCommand(3, 'ROUTE_A')">Route A (Express)</button>
                <button onclick="sendCommand(3, 'ROUTE_B')">Route B (Local)</button>
                <button onclick="sendCommand(3, 'ROUTE_C')">Route C (Maint)</button>
            </div>
        </div>
        
        <div class="log-panel">
            <h3>📋 Command Log</h3>
            <div id="log-content"></div>
        </div>
    </div>
    
    <script>
        async function updateStatus() {
            try {
                const resp = await fetch('/api/overview');
                const data = await resp.json();
                
                // Update master status
                const masterStatus = data.master_plc.error ? 
                    '<span class="error">OFFLINE</span>' : 
                    '<span class="success">ONLINE</span>';
                document.getElementById('master-status').innerHTML = masterStatus;
                
                // Update segments
                if (data.master_plc.segments) {
                    data.master_plc.segments.forEach(seg => {
                        const segDiv = document.getElementById(`seg${seg.segment_id}-status`);
                        segDiv.innerHTML = `
                            State: <span class="info">${seg.state}</span><br>
                            Route: <span class="warning">${seg.current_route || 'NONE'}</span><br>
                            Occupied: <span class="${seg.sensor_occupied ? 'error' : 'success'}">${seg.sensor_occupied ? 'YES' : 'NO'}</span>
                        `;
                    });
                }
                
                // Update command log
                const logDiv = document.getElementById('log-content');
                const commands = data.recent_commands || [];
                logDiv.innerHTML = commands.reverse().map(cmd => `
                    <div class="log-entry ${cmd.result.success ? 'success' : 'error'}">
                        [${cmd.timestamp}] Segment ${cmd.segment_id}: ${cmd.route} - ${cmd.result.success ? 'SUCCESS' : 'REJECTED'}
                    </div>
                `).join('');
                
                document.getElementById('command-count').textContent = commands.length;
                
            } catch (e) {
                console.error('Update failed:', e);
            }
        }
        
        async function sendCommand(segment_id, route) {
            try {
                const resp = await fetch('/api/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ segment_id, route })
                });
                const data = await resp.json();
                updateStatus();
            } catch (e) {
                alert('Command failed: ' + e);
            }
        }
        
        // Update clock
        setInterval(() => {
            const now = new Date();
            document.getElementById('system-time').textContent = 
                now.toLocaleTimeString();
        }, 1000);
        
        // Initial update and refresh every 2 seconds
        updateStatus();
        setInterval(updateStatus, 2000);
    </script>
</body>
</html>
'''

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/', methods=['GET'])
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'role': 'scada'})

@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify(scada.get_system_overview())

@app.route('/api/overview', methods=['GET'])
def api_overview():
    return jsonify(scada.get_system_overview())

@app.route('/api/command', methods=['POST'])
def api_command():
    data = request.json
    segment_id = data.get('segment_id')
    route = data.get('route')
    
    result = scada.send_route_command(segment_id, route)
    return jsonify(result)

@app.route('/api/segments', methods=['GET'])
def api_segments():
    return jsonify(scada.segments)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    logger.info("Starting SCADA Server on 0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=False)
