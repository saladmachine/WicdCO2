# module_datalogger.py
import os
import time
import re
from module_base import WicdpicoModule
from adafruit_httpserver import Request, Response, GET, POST

class DataloggerModule(WicdpicoModule):
    """
    A module for manual and automatic data logging to an SD card.
    Dynamically maps the output file and parses sensor dictionaries.
    """

    def __init__(self, foundation):
        super().__init__()
        self.foundation = foundation
        self.name = "Data Logger"
        self.version = "v2.6 (Dynamic Minified)"
        
        # Dynamically retrieve SYSTEM_NAME from settings.toml
        try:
            sys_name = getattr(self.foundation.config, 'SYSTEM_NAME', 'wicd_default')
            # Clean the string for filesystem compatibility
            clean_name = str(sys_name).lower().replace(" ", "_")
        except Exception:
            clean_name = "wicd_error"
            
        # Format the file path using f-strings
        self.log_file_path = f"/sd/{clean_name}_log.csv"
        
        # State variables for automatic logging
        self.is_logging = False
        self.log_interval = 60  # Default interval in seconds
        self.last_log_time = 0

    def get_routes(self):
        return [
            ("/log-data", self.handle_log_request),
            ("/start-logging", self.start_logging),
            ("/stop-logging", self.stop_logging),
            ("/select-log-file", self.select_log_file),
        ]

    def register_routes(self, server):
        """Registers all endpoints for the logger."""
        for route, handler in self.get_routes():
            server.route(route, methods=[POST])(handler)
        server.route("/list-log-files", methods=[GET])(self.list_log_files)
            
    def _perform_log(self):
        """Dynamically gathers data and writes a row to the CSV. Returns status string."""
        sd_manager = self.foundation.get_module('sd_manager')
        sd_ok = sd_manager and sd_manager.card_available

        rtc = self.foundation.get_module('rtc')
        
        # Dynamic Registry Targeting: Pull target key from config, default to 'sensor'
        target_sensor_key = getattr(self.foundation.config, 'PRIMARY_SENSOR_KEY', 'sensor')
        sensor = self.foundation.get_module(target_sensor_key)
        
        if not rtc: return "Error: RTC module missing."
        if not sensor: return f"Error: Target sensor '{target_sensor_key}' missing."

        try:
            timestamp = rtc.get_formatted_utc_time()
        except Exception:
            timestamp = "1970-01-01T00:00:00Z"

        # Dynamic Payload Parsing
        try:
            sensor_data = sensor.get_reading()
            if not sensor_data or not isinstance(sensor_data, dict):
                print("[DataLog Debug] get_reading returned None or non-dictionary")
                sensor_data = {"data_error": "N/A"}
        except Exception as e:
            print(f"[DataLog Debug] Sensor Read Error: {e}")
            sensor_data = {"data_error": "N/A"}

        # Sort keys to guarantee CSV column alignment over multiple write cycles
        data_keys = sorted(sensor_data.keys())
        data_values = [str(sensor_data[k]) for k in data_keys]

        # Generate CSV row dynamically
        csv_row = f"{timestamp},{','.join(data_values)}\n"

        if sd_ok:
            try:
                header_needed = False
                try:
                    os.stat(self.log_file_path)
                except OSError:
                    header_needed = True

                with open(self.log_file_path, "a") as f:
                    if header_needed:
                        # Generate CSV header dynamically
                        header = f"Timestamp_UTC,{','.join(data_keys)}\n"
                        f.write(header)
                    f.write(csv_row)
                return f"Logged to SD: {len(data_keys)} parameters"
            except Exception as e:
                return f"Error writing to file: {e}"
        else:
            print(f"[DataLog] {csv_row.strip()}")
            return f"SD Missing - Logged to Console: {len(data_keys)} parameters"

    def handle_log_request(self, request: Request):
        """Handles the 'Log Data' button press."""
        result = self._perform_log()
        return Response(request, result, content_type="text/plain")

    def start_logging(self, request: Request):
        """Handles the 'Start Log' button press."""
        sd_manager = self.foundation.get_module('sd_manager')
        if not sd_manager or not sd_manager.card_available:
            pass 

        try:
            body = request.body.decode('utf-8')
            match = re.search(r'\d+', body)
            if match:
                interval = int(match.group(0))
            else:
                interval = 60
                
            if interval < 5: interval = 5 

            self.log_interval = interval
            self.is_logging = True
            self.last_log_time = time.monotonic() 
            return Response(request, f"Logging Started ({self.log_interval}s interval)", content_type="text/plain")
        except Exception as e:
            return Response(request, f"Error: {e}", content_type="text/plain")

    def stop_logging(self, request: Request):
        """Handles the 'Stop Log' button press."""
        self.is_logging = False
        return Response(request, "Logging Stopped.", content_type="text/plain")

    def list_log_files(self, request: Request):
        """Returns a JSON list of CSV files on the SD card."""
        try:
            files = [f for f in os.listdir("/sd") if f.endswith(".csv")]
            files.sort()
            current = self.log_file_path.replace("/sd/", "")
            file_list = ",".join([f'"{f}"' for f in files])
            return Response(request,
                f'{{"current": "{current}", "files": [{file_list}]}}',
                content_type="application/json")
        except Exception as e:
            return Response(request, f'{{"error": "{e}"}}',
                            content_type="application/json")

    def select_log_file(self, request: Request):
        """Sets the active log file from a POST request."""
        try:
            body = request.body.decode("utf-8")
            match = re.search(r'filename=([^\s&]+)', body)
            if not match:
                return Response(request, "Error: No filename provided.",
                                content_type="text/plain")
            filename = match.group(1).strip()
            if not filename.endswith(".csv"):
                return Response(request, "Error: File must be a .csv file.",
                                content_type="text/plain")
            self.log_file_path = f"/sd/{filename}"
            return Response(request, f"Log file set to: {filename}",
                            content_type="text/plain")
        except Exception as e:
            return Response(request, f"Error: {e}", content_type="text/plain")

    def update(self):
        """Called continuously by the main loop to handle the timer."""
        if self.is_logging:
            now = time.monotonic()
            if (now - self.last_log_time) > self.log_interval:
                self._perform_log()
                self.last_log_time = now

    def get_dashboard_html(self):
        """Generates the HTML dashboard card for the logger."""
        btn_text = "Stop Log" if self.is_logging else "Start Log"
        btn_disabled = "disabled" if self.is_logging else ""

        return f"""<div class="module"><h2>{self.name}</h2><div class="control-group"><p><strong>Manual Log:</strong></p><button id="log-data-btn" onclick="logDataNow()">Log Data Now</button></div><div class="control-group" style="margin-top:15px;border-top:1px solid #eee;padding-top:15px;"><p><strong>Automatic Logging:</strong></p><label for="log-interval">Log every (seconds):</label><input type="number" id="log-interval" value="{self.log_interval}" style="width:80px;padding:5px;" {btn_disabled}><button id="toggle-log-btn" onclick="toggleLogging()">{btn_text}</button></div><div class="control-group" style="margin-top:15px;border-top:1px solid #eee;padding-top:15px;"><p><strong>Log File:</strong></p><select id="log-file-select" style="width:100%;padding:5px;margin-bottom:8px;"></select><button onclick="selectLogFile()">Use This File</button></div><p id="log-status" style="font-size:0.9em;min-height:20px;"></p></div><script>function logDataNow(){{const btn=document.getElementById('log-data-btn');const statusEl=document.getElementById('log-status');btn.disabled=true;btn.textContent='Logging...';statusEl.textContent='';fetch('/log-data',{{method:'POST'}}).then(r=>r.text()).then(result=>{{statusEl.textContent=result;statusEl.style.color=result.startsWith('Error')?'red':'green';}}).catch(err=>{{statusEl.textContent='Error: '+err.message;statusEl.style.color='red';}}).finally(()=>{{btn.disabled=false;btn.textContent='Log Data Now';}});}}function toggleLogging(){{const btn=document.getElementById('toggle-log-btn');const statusEl=document.getElementById('log-status');const intervalInput=document.getElementById('log-interval');const isLogging=btn.textContent==='Stop Log';btn.disabled=true;statusEl.textContent='';if(isLogging){{fetch('/stop-logging',{{method:'POST'}}).then(r=>r.text()).then(result=>{{statusEl.textContent=result;statusEl.style.color='orange';btn.textContent='Start Log';intervalInput.disabled=false;}}).catch(err=>{{statusEl.textContent='Error: '+err.message;}});}}else{{const interval=intervalInput.value;fetch('/start-logging',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{interval:interval}})}}).then(r=>r.text()).then(result=>{{statusEl.textContent=result;statusEl.style.color='green';btn.textContent='Stop Log';intervalInput.disabled=true;}}).catch(err=>{{statusEl.textContent='Error: '+err.message;}});}}btn.disabled=false;}}function loadLogFiles(){{fetch('/list-log-files').then(r=>r.json()).then(d=>{{const sel=document.getElementById('log-file-select');sel.innerHTML='';if(d.files){{d.files.forEach(f=>{{const opt=document.createElement('option');opt.value=f;opt.textContent=f;if(f===d.current)opt.selected=true;sel.appendChild(opt);}});}}}}).catch(err=>console.log('File list error:'+err));}}function selectLogFile(){{const sel=document.getElementById('log-file-select');const statusEl=document.getElementById('log-status');if(!sel.value)return;fetch('/select-log-file',{{method:'POST',body:'filename='+sel.value}}).then(r=>r.text()).then(result=>{{statusEl.textContent=result;statusEl.style.color=result.startsWith('Error')?'red':'green';}}).catch(err=>{{statusEl.textContent='Error: '+err.message;statusEl.style.color='red';}});}}loadLogFiles();</script>"""