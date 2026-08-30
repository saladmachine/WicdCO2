# module_scd30.py
# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: MIT

import time
import json
import adafruit_scd30
from module_base import WicdpicoModule
from adafruit_httpserver import Request, Response

class SCD30Module(WicdpicoModule):
    def __init__(self, i2c_bus):
        super().__init__()
        self.name = "SCD30 CO2 Sensor"
        self.i2c = i2c_bus
        self.sensor = None
        self.sensor_available = False
        self.last_reading = {"co2": 0, "temp": 0, "humidity": 0}
        
        # FRC State Machine Variables
        self.frc_state = "IDLE"
        self.frc_target_ppm = 400
        self.frc_timer_start = 0
        self.frc_wait_time = 120
        
        self.status_message = "Initializing..."
        self._initialize_sensor()

    def _initialize_sensor(self):
        if self.i2c is None:
            self.status_message = "Error: No I2C Bus"
            print("✗ SCD30: No I2C bus available")
            return
            
        try:
            self.sensor = adafruit_scd30.SCD30(self.i2c)
            
            # Disable ASC immediately on init.
            # This is critical for growth chamber use to prevent corrupted EEPROM gain baselines.
            self.sensor.self_calibration_enabled = False

            # FIX: The stress tests fundamentally altered the sensor's EEPROM interval to 5s.
            # We MUST explicitly force it back to 2s to guarantee normal continuous mode behavior.
            self.sensor.measurement_interval = 2
            
            self.sensor_available = True
            self.status_message = "Ready"
            print("✓ SCD30 sensor initialized (ASC Disabled)")
        except Exception as e:
            self.status_message = "Error: Init Failed"
            print("✗ SCD30 init failed: {}".format(e))
            self.sensor_available = False

    def get_reading(self):
        if not self.sensor_available:
            return None
            
        # SCD30 updates every ~2 seconds. We just read the current buffer.
        if self.sensor.data_available:
            try:
                self.last_reading = {
                    "co2": int(self.sensor.CO2),
                    "temp": round(self.sensor.temperature, 1),
                    "humidity": round(self.sensor.relative_humidity, 1)
                }
                return self.last_reading
            except Exception as e:
                print("SCD30 read error: {}".format(e))
        
        return self.last_reading

    def register_routes(self, server):
        @server.route("/sensor/data", methods=['GET'])
        def api_sensor_data(request: Request):
            data = self.get_reading()
            if data:
                json_str = '{{"co2": {}, "temp": {}, "humidity": {}}}'.format(
                    data["co2"], data["temp"], data["humidity"]
                )
                return Response(request, json_str, content_type="application/json")
            return Response(request, '{"error": "Sensor unavailable"}', content_type="application/json")

        @server.route("/scd30/data", methods=['GET'])
        def api_data(request: Request):
            data = self.get_reading()
            if data:
                json_str = '{{"co2": {}, "temp": {}, "humidity": {}}}'.format(
                    data["co2"], data["temp"], data["humidity"]
                )
                return Response(request, json_str, content_type="application/json")
            return Response(request, '{"error": "Sensor unavailable"}', content_type="application/json")

        # --- FRC Dedicated Page Route ---
        @server.route("/scd30/calibrate", methods=['GET'])
        def serve_frc_page(request: Request):
            html = """<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <!-- Ensure correct scaling on mobile devices -->
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>SCD30 FRC Calibration</title>
                <style>
                    body { font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; background-color: #f8f9fa;}
                    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
                    .module { background: white; padding: 20px; border-radius: 8px; border: 1px solid #ddd; box-shadow: 0 2px 4px rgba(0,0,0,0.1);}
                    button { padding: 8px 16px; cursor: pointer; border: 1px solid #ccc; border-radius: 4px; background-color: #e9ecef;}
                    button:hover { background-color: #d3d9df; }
                    .btn-danger { background-color: #dc3545; color: white; border: none; }
                    .btn-success { background-color: #28a745; color: white; border: none; font-weight: bold; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>SCD30 Forced Recalibration</h2>
                    <!-- Return button attempts to close tab first, then falls back to history -->
                    <button onclick="window.close() || window.history.back()">Return to Dashboard</button>
                </div>
                <div class="module">
                    <p style="font-size: 0.9em; color: #555; margin-bottom: 15px;">
                        To calibrate, you must either expose the device to ambient air and set the reference CO2 to 400ppm or use an external reference instrument (e.g., LI-850). The sensor must stabilize for 2 minutes prior to executing the write command.
                    </p>
                    
                    <div id="frc-idle-view">
                        <label style="font-weight: bold;">Reference CO2 (ppm): </label>
                        <input type="number" id="frc-target-input" value="400" style="width: 80px; padding: 6px; border: 1px solid #ccc; border-radius: 4px;">
                        <button onclick="startFRC()" style="margin-left: 10px; background-color: #007bff; color: white; border: none;">Initiate Calibration</button>
                    </div>
                    
                    <div id="frc-waiting-view" style="display: none; background: #e2e3e5; padding: 15px; border-left: 4px solid #6c757d; border-radius: 4px;">
                        <strong>Stabilizing Sensor Environment</strong><br><br>
                        Target Reference: <span id="frc-waiting-target"></span> ppm<br>
                        Time Remaining: <strong style="color: #dc3545; font-size: 1.2em;"><span id="frc-time-left"></span> seconds</strong><br><br>
                        <button class="btn-danger" onclick="cancelFRC()">Abort Calibration</button>
                    </div>
                    
                    <div id="frc-ready-view" style="display: none; background: #d4edda; padding: 15px; border-left: 4px solid #28a745; border-radius: 4px;">
                        <strong style="color: #155724; font-size: 1.1em;">Ready to Calibrate</strong><br><br>
                        Reference Target: <strong id="frc-ready-target"></strong> ppm<br>
                        SCD30 Live Reading: <strong id="frc-ready-live"></strong> ppm<br><br>
                        <div>
                            <button class="btn-success" onclick="commitFRC()">Confirm & Write FRC</button>
                            <button onclick="cancelFRC()" style="margin-left: 10px;">Cancel</button>
                        </div>
                    </div>
                    
                    <p id="frc-msg" style="font-size: 1em; font-weight: bold; margin-top: 15px; color: #0056b3;"></p>
                </div>
                
                <script>
                let frcInterval = null;
                
                function updateFRCUI(data) {
                    document.getElementById('frc-idle-view').style.display = data.state === 'IDLE' ? 'block' : 'none';
                    document.getElementById('frc-waiting-view').style.display = data.state === 'WAITING' ? 'block' : 'none';
                    document.getElementById('frc-ready-view').style.display = data.state === 'READY' ? 'block' : 'none';
                    
                    if (data.state === 'WAITING') {
                        document.getElementById('frc-time-left').innerText = data.remaining;
                        document.getElementById('frc-waiting-target').innerText = data.target;
                    } else if (data.state === 'READY') {
                        document.getElementById('frc-ready-target').innerText = data.target;
                        document.getElementById('frc-ready-live').innerText = data.current_co2;
                    }
                    
                    if (data.state === 'IDLE') {
                        if (frcInterval) { clearInterval(frcInterval); frcInterval = null; }
                    } else {
                        if (!frcInterval) { frcInterval = setInterval(pollFRCStatus, 1000); }
                    }
                }
                
                function pollFRCStatus() {
                    fetch('/scd30/frc/status')
                        .then(r => r.json())
                        .then(d => updateFRCUI(d))
                        .catch(e => console.error("FRC Poll Error: ", e));
                }
                
                function startFRC() {
                    const target = document.getElementById('frc-target-input').value;
                    document.getElementById('frc-msg').innerText = '';
                    fetch('/scd30/frc/start', {
                        method: 'POST',
                        body: JSON.stringify({ppm: parseInt(target)})
                    }).then(() => pollFRCStatus());
                }
                
                function cancelFRC() {
                    document.getElementById('frc-msg').innerText = 'Calibration aborted.';
                    fetch('/scd30/frc/cancel', {method: 'POST'}).then(() => pollFRCStatus());
                }
                
                function commitFRC() {
                    document.getElementById('frc-msg').innerText = 'Writing calibration reference to EEPROM...';
                    fetch('/scd30/frc/commit', {method: 'POST'})
                        .then(r => r.json())
                        .then(d => {
                            if (d.error) {
                                document.getElementById('frc-msg').style.color = '#dc3545';
                                document.getElementById('frc-msg').innerText = 'Error: ' + d.error;
                            } else {
                                document.getElementById('frc-msg').style.color = '#28a745';
                                document.getElementById('frc-msg').innerText = 'FRC calibration successful.';
                                pollFRCStatus();
                            }
                        });
                }
                
                pollFRCStatus();
                </script>
            </body>
            </html>"""
            return Response(request, html, content_type="text/html")

        # --- FRC API Endpoints ---
        @server.route("/scd30/frc/start", methods=['POST'])
        def api_frc_start(request: Request):
            try:
                payload = json.loads(request.body)
                self.frc_target_ppm = int(payload.get("ppm", 400))
                self.frc_state = "WAITING"
                self.frc_timer_start = time.monotonic()
                return Response(request, '{"status": "waiting"}', content_type="application/json")
            except Exception as e:
                return Response(request, '{{"error": "Invalid payload: {}"}}'.format(e), content_type="application/json")

        @server.route("/scd30/frc/status", methods=['GET'])
        def api_frc_status(request: Request):
            if self.frc_state == "IDLE":
                remaining = 0
            else:
                elapsed = time.monotonic() - self.frc_timer_start
                remaining = max(0, self.frc_wait_time - int(elapsed))
                
                if self.frc_state == "WAITING" and remaining == 0:
                    self.frc_state = "READY"
                    
            resp_str = '{{"state": "{}", "remaining": {}, "target": {}, "current_co2": {}}}'.format(
                self.frc_state, remaining, self.frc_target_ppm, self.last_reading.get("co2", 0)
            )
            return Response(request, resp_str, content_type="application/json")

        @server.route("/scd30/frc/commit", methods=['POST'])
        def api_frc_commit(request: Request):
            if self.frc_state == "READY" and self.sensor_available:
                try:
                    self.sensor.self_calibration_enabled = False
                    self.sensor.forced_recalibration_reference = self.frc_target_ppm
                    self.frc_state = "IDLE"
                    return Response(request, '{"status": "success"}', content_type="application/json")
                except Exception as e:
                    return Response(request, '{{"error": "Write failed: {}"}}'.format(e), content_type="application/json")
            return Response(request, '{"error": "Sensor not ready"}', content_type="application/json")

        @server.route("/scd30/frc/cancel", methods=['POST'])
        def api_frc_cancel(request: Request):
            self.frc_state = "IDLE"
            return Response(request, '{"status": "cancelled"}', content_type="application/json")

    def get_dashboard_html(self):
        status_color = "#28a745" if self.sensor_available else "#dc3545"
        cur = self.last_reading
        
        return """
        <div class="module">
            <h3>SCD30 Sensor</h3>
            <div style="border-left: 6px solid {status_color}; padding-left: 12px; margin-bottom: 15px;">
                <strong>Status:</strong> {status}
            </div>
            
            <div style="text-align: center; margin: 20px 0;">
                <div style="font-size: 4em; font-weight: bold; line-height: 1;">
                    <span id="scd30-co2">{co2}</span><span style="font-size: 0.5em; margin-left: 8px; color: #555;">ppm</span>
                </div>
            </div>
            
            <p style="text-align: center; font-size: 1em; color: #666; margin-bottom: 5px;">
                Temperature and RH are for the sensor, not the surrounding environment
            </p>
            
            <p style="font-size: 1.2em; text-align: center; margin-top: 0;">
                <span id="scd30-temp">{temp}</span> °C, <span id="scd30-hum">{hum}</span>% RH
            </p>
            
            <!-- Flexbox applied here to center and align the buttons evenly side-by-side -->
            <div style="display: flex; justify-content: center; gap: 10px; margin-top: 15px; align-items: center;">
                <button onclick="fetchSCD30()" style="padding: 8px 16px; cursor: pointer;">Update Reading</button>
                <button onclick="window.open('/scd30/calibrate', '_blank')" style="padding: 8px 16px; cursor: pointer;">Launch FRC Calibration</button>
            </div>
            <p id="scd30-debug" style="font-size: 0.8em; color: #666; min-height: 1.2em; text-align: center; margin-top: 10px;"></p>
            
            <script>
            function fetchSCD30() {{
                const debug = document.getElementById('scd30-debug');
                debug.innerText = "Fetching...";
                fetch('/scd30/data')
                    .then(r => r.json())
                    .then(d => {{
                        if(d.error) {{
                            debug.innerText = "Error: " + d.error;
                        }} else {{
                            document.getElementById('scd30-co2').innerText = d.co2;
                            document.getElementById('scd30-temp').innerText = d.temp;
                            document.getElementById('scd30-hum').innerText = d.humidity;
                            debug.innerText = "Updated " + new Date().toLocaleTimeString();
                        }}
                    }})
                    .catch(e => {{ debug.innerText = "Network Error"; }});
            }}
            </script>
        </div>
        """.format(
            status_color=status_color, 
            status=self.status_message, 
            co2=cur['co2'],
            temp=cur['temp'],
            hum=cur['humidity']
        )

    def update(self):
        # Optional: Periodic background tasks
        pass