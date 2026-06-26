#!/usr/bin/env python3
"""
Railroad North - Slave PLC
Local track segment controller
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Dict
from flask import Flask, jsonify, request
import threading

logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATA STRUCTURES
# ============================================================================

class DeviceType(Enum):
    TRACK_SWITCH = 1
    SIGNAL = 2
    BARRIER = 3
    OCCUPANCY_SENSOR = 4

class SignalState(Enum):
    RED = 0
    YELLOW = 1
    GREEN = 2

@dataclass
class LocalDevice:
    device_id: int
    device_type: DeviceType
    name: str
    state: any
    last_update: datetime

# ============================================================================
# SLAVE PLC CLASS
# ============================================================================

class SlavePLC:
    """
    Slave PLC for track segment control
    """
    
    def __init__(self):
        self.slave_id = int(os.environ.get('SLAVE_ID', 1))
        self.segment_name = os.environ.get('SEGMENT_NAME', 'Unknown')
        self.master_ip = os.environ.get('MASTER_IP', '172.25.0.10')
        self.master_port = int(os.environ.get('MASTER_PORT', 502))
        self.listen_port = int(os.environ.get('LISTEN_PORT', 502))
        
        # Load segment configuration
        self.config = self._load_config()
        
        # Initialize devices
        self.devices: Dict[int, LocalDevice] = {}
        self.initialize_devices()
        
        # Operational state
        self.last_master_contact = datetime.now()
        self.heartbeat_interval = 5
        
        logger.info(f"Slave PLC {self.slave_id} ({self.segment_name}) initialized")
    
    def _load_config(self) -> Dict:
        """Load segment configuration"""
        try:
            with open('/app/config/segment.json') as f:
                return json.load(f)
        except:
            logger.warning("Segment config not found, using defaults")
            return {
                'segment_id': self.slave_id,
                'name': self.segment_name,
                'devices': [
                    {'id': 1, 'type': 'TRACK_SWITCH', 'name': f'Switch {self.segment_name}-A'},
                    {'id': 2, 'type': 'TRACK_SWITCH', 'name': f'Switch {self.segment_name}-B'},
                    {'id': 3, 'type': 'SIGNAL', 'name': f'Signal {self.segment_name}'},
                    {'id': 4, 'type': 'BARRIER', 'name': f'Barrier {self.segment_name}'},
                    {'id': 5, 'type': 'OCCUPANCY_SENSOR', 'name': f'Occupancy {self.segment_name}'},
                ]
            }
    
    def initialize_devices(self):
        """Initialize local devices"""
        for dev_config in self.config.get('devices', []):
            dev_id = dev_config['id']
            dev_type = DeviceType[dev_config['type']]
            
            # Initialize with default state
            if dev_type == DeviceType.TRACK_SWITCH:
                initial_state = 'INACTIVE'
            elif dev_type == DeviceType.SIGNAL:
                initial_state = SignalState.RED
            elif dev_type == DeviceType.BARRIER:
                initial_state = 'LOWERED'
            elif dev_type == DeviceType.OCCUPANCY_SENSOR:
                initial_state = False  # Not occupied
            else:
                initial_state = None
            
            self.devices[dev_id] = LocalDevice(
                device_id=dev_id,
                device_type=dev_type,
                name=dev_config['name'],
                state=initial_state,
                last_update=datetime.now()
            )
    
    async def control_track_switch(self, switch_id: int, command: str) -> bool:
        """Control track switch"""
        if switch_id not in self.devices:
            logger.error(f"Unknown switch {switch_id}")
            return False
        
        device = self.devices[switch_id]
        
        if device.device_type != DeviceType.TRACK_SWITCH:
            logger.error(f"Device {switch_id} is not a track switch")
            return False
        
        # Validate command
        if command not in ['ACTIVATE', 'DEACTIVATE']:
            logger.error(f"Invalid command: {command}")
            return False
        
        # Check safety conditions
        if command == 'ACTIVATE':
            # Check if track is occupied
            occupancy_sensor = next(
                (d for d in self.devices.values() 
                 if d.device_type == DeviceType.OCCUPANCY_SENSOR),
                None
            )
            
            if occupancy_sensor and occupancy_sensor.state:
                logger.warning(f"Cannot activate switch {switch_id}: track occupied")
                return False
            
            # Check barrier status
            barrier = next(
                (d for d in self.devices.values() 
                 if d.device_type == DeviceType.BARRIER),
                None
            )
            
            if barrier and barrier.state != 'LOWERED':
                logger.warning(f"Cannot activate switch {switch_id}: barrier not lowered")
                return False
        
        # Execute command
        device.state = 'ACTIVE' if command == 'ACTIVATE' else 'INACTIVE'
        device.last_update = datetime.now()
        
        logger.info(f"Switch {switch_id} ({device.name}) {command}")
        
        # Send audit log
        await self.send_audit_log(
            f"DEVICE_CONTROL: {device.name} {command}"
        )
        
        return True
    
    async def control_signal(self, signal_state: SignalState) -> bool:
        """Control signal light"""
        signal = next(
            (d for d in self.devices.values() 
             if d.device_type == DeviceType.SIGNAL),
            None
        )
        
        if not signal:
            return False
        
        signal.state = signal_state
        signal.last_update = datetime.now()
        
        logger.info(f"Signal {signal.name} set to {signal_state.name}")
        
        await self.send_audit_log(f"SIGNAL_CHANGE: {signal.name} -> {signal_state.name}")
        
        return True
    
    async def send_audit_log(self, message: str):
        """Send audit log to collector"""
        timestamp = datetime.now().isoformat()
        log_message = f"{timestamp} [SLAVE-{self.slave_id}] {message}"
        
        try:
            # Send via syslog to collector
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(log_message.encode(), ('172.25.0.40', 514))
            sock.close()
        except Exception as e:
            logger.error(f"Failed to send audit log: {e}")
    
    def get_status(self) -> Dict:
        """Get segment status"""
        return {
            'slave_id': self.slave_id,
            'segment_name': self.segment_name,
            'timestamp': datetime.now().isoformat(),
            'devices': {
                dev_id: {
                    'id': dev.device_id,
                    'name': dev.name,
                    'type': dev.device_type.name,
                    'state': str(dev.state),
                    'last_update': dev.last_update.isoformat()
                }
                for dev_id, dev in self.devices.items()
            }
        }

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__)
slave_plc = SlavePLC()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'role': 'slave', 'slave_id': slave_plc.slave_id})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(slave_plc.get_status())

@app.route('/api/device/switch', methods=['POST'])
def control_switch():
    data = request.json
    switch_id = data.get('switch_id')
    command = data.get('command')
    
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(slave_plc.control_track_switch(switch_id, command))
    loop.close()
    
    return jsonify({'success': result})

@app.route('/api/device/signal', methods=['POST'])
def control_signal():
    data = request.json
    state = SignalState[data.get('state')]
    
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(slave_plc.control_signal(state))
    loop.close()
    
    return jsonify({'success': result})

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    logger.info(f"Starting Slave {slave_plc.slave_id} API on 0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
