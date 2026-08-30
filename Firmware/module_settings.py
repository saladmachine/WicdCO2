# module_settings.py
# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: MIT

import microcontroller
import os
import time
from module_base import WicdpicoModule
from adafruit_httpserver import Response

class SettingsModule(WicdpicoModule):
    def __init__(self, foundation):
        super().__init__(foundation=foundation)
        self.foundation = foundation
        self.name = "System Configuration"
        self.sd_path = "/sd/SD_Override.toml"
        
    def get_dashboard_html(self):
        """Standard dashboard card."""
        return """
        <div class="module">
            <h3>Configuration</h3>
            <p><strong>Config Mode:</strong> Tier 2 (SD Priority)</p>
            <div class="control-group">
                <a href="/settings"><button>Edit System Settings</button></a>
            </div>
            <hr>
            <div class="control-group">
                <button onclick="rebootSystem()" style="background-color: #dc3545;">Reboot System</button>
            </div>
            <hr>
            <div class="control-group">
                 <button onclick="syncTime()" style="background-color: #17a2b8;">Sync Time from Browser</button>
            </div>
            <script>
            function rebootSystem() {
                if(confirm('Are you sure you want to REBOOT the device?')) {
                    fetch('/system/reboot', {method: 'POST'})
                    .then(r => alert('Rebooting... Connection will be lost.'))
                    .catch(e => alert('Reboot command sent.'));
                }
            }
            function syncTime() {
                const now = Math.floor(Date.now() / 1000); // Unix timestamp in seconds
                fetch('/system/set-time?timestamp=' + now, {method: 'POST'})
                .then(r => r.text())
                .then(msg => alert(msg))
                .catch(e => alert('Error syncing time: ' + e));
            }
            </script>
        </div>
        """

    def get_routes(self):
        return [
            ("/settings", self.settings_page),
            ("/settings/save", self.save_settings),
            ("/system/reboot", self.handle_reboot),
            ("/system/set-time", self.handle_set_time)
        ]

    def register_routes(self, server):
        for route, handler in self.get_routes():
            server.route(route, methods=['GET', 'POST'])(handler)

    def handle_reboot(self, request):
        """Triggers a hard system reset."""
        # Schedule the reset slightly in future to allow response to send
        # In CircuitPython we can't easily schedule, so we just return response then hope for best.
        # Ideally we would use an async task, but here we will return headers then reset.
        # Actually, let's just do it.
        # A dirty hack is needed to let the response flush.
        try:
             # We can't really flush, so we just reset.
             # The client side JS alert will have to suffice.
             pass
        except:
            pass
        
        # We perform the reset AFTER this function returns via a "dirty" timer?
        # No, we can't. We will just reset. The browser will see network error.
        # Better: Return a response, and in the "poll" loop check a flag?
        # Let's use a flag in the module.
        self.reboot_pending = True
        return Response(request, "Rebooting...", content_type="text/plain")

    def handle_set_time(self, request):
        """Set RTC from browser timestamp."""
        try:
            params = request.query_params
            timestamp = int(params.get('timestamp', 0))
            if timestamp == 0:
                 return Response(request, "Error: Invalid timestamp", content_type="text/plain")
            
            # Update RTC
            # We need to access the RTC object. It's usually in DarkBoxModule, but we can try to find it via Foundation or just re-init it?
            # Better: Foundation should expose RTC if possible.
            # Workaround: Re-init PCF8523 here just for the update.
            import board
            import busio
            from adafruit_pcf8523.pcf8523 import PCF8523
            
            i2c = self.foundation.i2c
            if not i2c:
                 return Response(request, "Error: I2C not available", content_type="text/plain")
            
            rtc = PCF8523(i2c)
            # Convert timestamp to struct_time
            tm = time.localtime(timestamp)
            rtc.datetime = tm
            
            return Response(request, "Time Updated: " + str(tm), content_type="text/plain")
        except Exception as e:
            return Response(request, "Error setting time: " + str(e), content_type="text/plain")

    def update(self):
        """Check for pending reboot"""
        if getattr(self, 'reboot_pending', False):
            # Wait a tick to let network buffers flush?
            time.sleep(0.5) 
            microcontroller.reset()

    def settings_page(self, request):
        """Render the full settings form."""
        
        # Read current effective config
        current_ssid = self.foundation.config.WIFI_SSID
        current_sysname = self.foundation.config.SYSTEM_NAME
        current_tz = self.foundation.config.TIMEZONE_OFFSET_HOURS
        current_sensor = getattr(self.foundation.config, 'ACTIVE_SENSOR', 'SCD30').upper()
        # We don't display password for security, leave blank to keep unchanged?
        # Or just display it (since it's an admin panel).
        # Let's display it. It's a local device access point.
        current_pass = self.foundation.config.WIFI_PASSWORD

        html = """
        <div class="module">
            <h2>System Configuration</h2>
            <div class="status" style="border-left: 5px solid #ffc107; background: #fff3cd; color: #856404;">
                <strong>IMPORTANT:</strong> Settings are saved to the <strong>SD Card</strong>.
                <ul>
                    <li>If you enter a wrong password, you will be locked out.</li>
                    <li><strong>To Recover:</strong> Eject the SD card and Reboot. The system will revert to Factory Defaults.</li>
                </ul>
            </div>
            
            <form action="/settings/save" method="POST">
                
                <label><strong>System Name:</strong></label><br>
                <input type="text" name="SYSTEM_NAME" value="{sysname}" style="width: 100%; padding: 8px; margin: 5px 0;"><br><br>
                
                <label><strong>WiFi SSID (Network Name):</strong></label><br>
                <input type="text" name="WIFI_SSID" value="{ssid}" style="width: 100%; padding: 8px; margin: 5px 0;"><br><br>
                
                <label><strong>WiFi Password:</strong></label><br>
                <input type="text" name="WIFI_PASSWORD" value="{pwd}" style="width: 100%; padding: 8px; margin: 5px 0;"><br><br>
                
                <label><strong>Timezone Offset (Hours):</strong></label><br>
                <input type="number" name="TIMEZONE_OFFSET_HOURS" value="{tz}" style="width: 100%; padding: 8px; margin: 5px 0;"><br><br>
                
                <label><strong>Active Sensor Hardware:</strong></label><br>
                <select name="ACTIVE_SENSOR" style="width: 100%; padding: 8px; margin: 5px 0;">
                    <option value="SCD30" {scd30_sel}>SCD30 (Default)</option>
                    <option value="SCD41" {scd41_sel}>SCD41</option>
                </select><br><br>
                
                <hr>
                <button type="submit" style="background-color: #28a745;">Save Settings & Reboot</button>
                <a href="/"><button type="button" style="background-color: #6c757d;">Cancel</button></a>
            </form>
        </div>
        """.format(
            sysname=current_sysname,
            ssid=current_ssid,
            pwd=current_pass,
            tz=current_tz,
            scd30_sel="selected" if current_sensor == "SCD30" else "",
            scd41_sel="selected" if current_sensor == "SCD41" else ""
        )
        
        return Response(request, self.foundation.templates.render_page("Settings", html), content_type="text/html")

    def save_settings(self, request):
        """Parse form data and write to SD card TOML."""
        
        # 1. Parse Form Data
        form_data = request.form_data
        if not form_data:
             return Response(request, "Error: No data received.", content_type="text/plain")

        new_sysname = form_data.get('SYSTEM_NAME', '').strip()
        new_ssid = form_data.get('WIFI_SSID', '').strip()
        new_pass = form_data.get('WIFI_PASSWORD', '').strip()
        new_tz = form_data.get('TIMEZONE_OFFSET_HOURS', '0').strip()
        new_sensor = form_data.get('ACTIVE_SENSOR', 'SCD30').strip().upper()

        # 2. Validation
        if len(new_pass) < 8:
             return Response(request, "Error: Password must be 8+ characters.", content_type="text/plain")

        # 3. Construct TOML Content
        toml_content = ""
        toml_content += '# WicdPico SD Override Configuration (Tier 2)\n'
        toml_content += '# Generated by Web Dashboard. Do not hand-edit.\n\n'
        toml_content += 'SYSTEM_NAME = "{}"\n'.format(new_sysname)
        toml_content += 'WIFI_SSID = "{}"\n'.format(new_ssid)
        toml_content += 'WIFI_PASSWORD = "{}"\n'.format(new_pass)
        toml_content += 'TIMEZONE_OFFSET_HOURS = {}\n'.format(new_tz)
        toml_content += 'ACTIVE_SENSOR = "{}"\n'.format(new_sensor)
        
        # 4. Write to SD
        try:
            # Check if SD is actually writable/mounted
            os.stat("/sd") 
            with open(self.sd_path, "w") as f:
                f.write(toml_content)
                
            # 5. Trigger Reboot
            self.reboot_pending = True
            
            return Response(request, "Settings Saved! Rebooting now...", content_type="text/plain")
            
        except Exception as e:
            return Response(request, "Error writing to SD Card: {}. Ensure SD is inserted.".format(e), content_type="text/plain")
