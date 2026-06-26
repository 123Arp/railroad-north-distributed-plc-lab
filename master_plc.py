#!/usr/bin/env python3
"""
Railroad North - Master PLC
Coordinates track segments and enforces safety interlocks
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from flask import Flask, jsonify, request
import threading

# Configure logging
logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATA STRUCTURES
# ============================================================================

class TrackState(Enum):
    """Track segment states"""
    IDLE = 0
    SWITCHING = 1
    OCCUPIED = 2
    FAULT = 3
    EMERGENCY_STOP = 4

class RouteType(Enum):
    """Route types in the network"""
    ROUTE_A = 1  # Express mainline
    ROUTE_B = 2  # Local siding
    ROUTE_C = 3  # Maintenance track

@dataclass
class SegmentStatus:
    """Status of a track segment"""
    segment_id: int
    name: str
    state: TrackState
    current_route: Optional[RouteType]
    last_switch_time: datetime
    sensor_occupied: bool
    barrier_engaged: bool
    signal_state: str
    fault_code: int

@dataclass
class SafetyInterlock:
    """Safety rule enforcement"""
    rule_id: int
    description: str
    condition: str
    action: str
    active: bool

# ============================================================================
# MASTER PLC CLASS
# ============================================================================

class MasterPLC:
    """
    Railroad North Master PLC Controller
    Manages distributed track segments with safety interlocks
    """
    
    def __init__(self):
        self.listen_ip = os.environ.get('LISTEN_IP', '0.0.0.0')
        self.listen_port = int(os.environ.get('LISTEN_PORT', 502))
        self.slave_configs = self._load_slave_configs()
        
        # Segment status tracking
        self.segments: Dict[int, SegmentStatus] = {}
        self.initialize_segments()
        
        # Safety interlocks
        self.safety_interlocks = self._load_safety_interlocks()
        
        # Communication history
        self.command_history: List[Dict] = []
        self.max_history = 1000
        
        logger.info("Master PLC initialized")
    
    def _load_slave_configs(self) -> Dict:
        """Load slave PLC configurations"""
        try:
            with open('/app/slave_config.json') as f:
                return json.load(f)
        except:
            logger.warning("Slave config not found, using defaults")
            return {
                'slaves': [
                    {'id': 1, 'name': 'North', 'ip': '172.25.1.10', 'port': 502},
                    {'id': 2, 'name': 'Central', 'ip': '172.25.2.10', 'port': 502},
                    {'id': 3, 'name': 'South', 'ip': '172.25.3.10', 'port': 502}
                ]
            }
    
    def initialize_segments(self):
        """Initialize track segments"""
        for slave in self.slave_configs['slaves']:
            segment_id = slave['id']
            self.segments[segment_id] = SegmentStatus(
                segment_id=segment_id,
                name=slave['name'],
                state=TrackState.IDLE,
                current_route=None,
                last_switch_time=datetime.now(),
                sensor_occupied=False,
                barrier_engaged=False,
                signal_state='RED',
                fault_code=0
            )
    
    def _load_safety_interlocks(self) -> List[SafetyInterlock]:
        """Define safety rules"""
        return [
            SafetyInterlock(
                rule_id=1,
                description="No conflicting routes at junction",
                condition="segment_2_route == A AND segment_1_route == A",
                action="REJECT_COMMAND",
                active=True
            ),
            SafetyInterlock(
                rule_id=2,
                description="Barrier must be lowered before routing",
                condition="barrier_not_engaged",
                action="REJECT_COMMAND",
                active=True
            ),
            SafetyInterlock(
                rule_id=3,
                description="No track switching when occupied",
                condition="track_occupied AND switch_command",
                action="ACTIVATE_EMERGENCY_STOP",
                active=True
            ),
            SafetyInterlock(
                rule_id=4,
                description="Heartbeat failure triggers E-stop",
                condition="slave_heartbeat_timeout > 5s",
                action="ACTIVATE_EMERGENCY_STOP",
                active=True
            ),
        ]
    
    def validate_route_command(self, segment_id: int, route: RouteType) -> tuple:
        """
        Validate route command against safety interlocks
        Returns: (is_valid: bool, reason: str)
        """
        
        # Check segment exists
        if segment_id not in self.segments:
            return False, f"Invalid segment ID: {segment_id}"
        
        segment = self.segments[segment_id]
        
        # Check if segment is in fault state
        if segment.state == TrackState.FAULT:
            return False, f"Segment {segment.name} is in FAULT state"
        
        # Check emergency stop
        if segment.state == TrackState.EMERGENCY_STOP:
            return False, f"Segment {segment.name} is under EMERGENCY STOP"
        
        # Check barrier engagement
        if not segment.barrier_engaged:
            return False, f"Barrier not engaged for segment {segment.name}"
        
        # Check track occupancy
        if segment.sensor_occupied and segment.state == TrackState.SWITCHING:
            return False, f"Cannot switch: track {segment.name} is occupied"
        
        # Check for route conflicts (simplified)
        if segment_id == 2:  # Central junction
            if segment.current_route == RouteType.ROUTE_A and route == RouteType.ROUTE_A:
                if self.segments[1].current_route == RouteType.ROUTE_A:
                    return False, "Conflicting routes at junction"
        
        return True, "Valid"
    
    async def execute_route_command(self, segment_id: int, route: RouteType) -> bool:
        """Execute a route change command"""
        
        # Validate
        is_valid, reason = self.validate_route_command(segment_id, route)
        
        command_log = {
            'timestamp': datetime.now().isoformat(),
            'segment_id': segment_id,
            'requested_route': route.name,
            'valid': is_valid,
            'reason': reason
        }
        
        if not is_valid:
            logger.warning(f"REJECTED: Segment {segment_id} route {route.name} - {reason}")
            self.command_history.append(command_log)
            return False
        
        # Update segment
        segment = self.segments[segment_id]
        segment.state = TrackState.SWITCHING
        segment.current_route = route
        segment.last_switch_time = datetime.now()
        
        logger.info(f"APPROVED: Segment {segment.name} route changed to {route.name}")
        
        # Simulate switching delay
        await asyncio.sleep(0.5)
        
        segment.state = TrackState.IDLE
        command_log['executed'] = True
        self.command_history.append(command_log)
        
        # Trim history
        if len(self.command_history) > self.max_history:
            self.command_history.pop(0)
        
        return True
    
    def get_system_status(self) -> Dict:
        """Get complete system status"""
        return {
            'timestamp': datetime.now().isoformat(),
            'segments': [
                {
                    'segment_id': seg.segment_id,
                    'name': seg.name,
                    'state': seg.state.name,
                    'current_route': seg.current_route.name if seg.current_route else None,
                    'sensor_occupied': seg.sensor_occupied,
                    'barrier_engaged': seg.barrier_engaged,
                    'signal_state': seg.signal_state
                }
                for seg in self.segments.values()
            ],
            'safety_interlocks': [
                {
                    'rule_id': si.rule_id,
                    'description': si.description,
                    'active': si.active
                }
                for si in self.safety_interlocks
            ],
            'total_commands': len(self.command_history),
            'recent_commands': self.command_history[-10:]
        }

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__)
master_plc = MasterPLC()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'role': 'master'})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(master_plc.get_system_status())

@app.route('/api/command', methods=['POST'])
def send_command():
    data = request.json
    segment_id = data.get('segment_id')
    route = RouteType[data.get('route')]
    
    # Execute synchronously for API
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        master_plc.execute_route_command(segment_id, route)
    )
    loop.close()
    
    return jsonify({'success': result})

@app.route('/api/segments', methods=['GET'])
def get_segments():
    segments = {
        seg_id: {
            'segment_id': seg.segment_id,
            'name': seg.name,
            'state': seg.state.name
        }
        for seg_id, seg in master_plc.segments.items()
    }
    return jsonify(segments)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    logger.info(f"Starting Master PLC on {master_plc.listen_ip}:{master_plc.listen_port}")
    logger.info("Starting Flask API on 0.0.0.0:8080")
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
