# module_wifi_manager.py
import time
import wifi
import board
import digitalio
import os
from module_base import WicdpicoModule
from adafruit_httpserver import Request, Response

class WifiManagerModule(WicdpicoModule):
    """
    Manages the Wi-Fi hotspot timeout feature.
    Dynamically tracks USB/Battery states and provides hardware wake interrupts.

    NOTE: This module owns GP13 exclusively. Do NOT register module_button.py
    in the same system — it claims the same pin and the same /button/state
    route, which will cause a hardware conflict and a route collision.

    Fixes applied (v2.4 -> v2.5):
        Bug 1: get_hotspot_status() was resetting last_activity_time to now
               before computing elapsed, so elapsed was always ~0 and the
               AP countdown never advanced while the browser was polling.
               Fix: removed the erroneous self.last_activity_time assignment.

        Bug 2: _wake_wifi_ap() called start_ap() but never called
               safe_set_ipv4_address(). After a timeout-and-wake cycle,
               192.168.4.1 was not reassigned and clients could not reconnect.
               Fix: added safe_set_ipv4_address() call after every AP restart.

        Bug 3: super().__init__() was called without foundation=foundation,
               inconsistent with every other module.
               Fix: super().__init__(foundation=foundation).

        Bug 4: Bare print() used inside update() for the button press event.
               Fix: replaced with self.foundation.startup_print().
    """
    DEBOUNCE_CYCLES = 3

    def __init__(self, foundation):
        super().__init__(foundation=foundation)          # FIX Bug 3
        self.foundation = foundation
        self.name = "WiFi Manager"
        self.version = "v2.5"

        self.timeout_disabled = True
        self.ap_is_off_and_logged = False
        self.user_override_active = False
        self.last_activity_time = time.monotonic()

        timeout_minutes = getattr(self.foundation.config, 'WIFI_AP_TIMEOUT_MINUTES', 15)
        self.timeout_seconds = timeout_minutes * 60

        self.toggle_state = False
        self.press_count = 0

        self.button = digitalio.DigitalInOut(board.GP13)
        self.button.direction = digitalio.Direction.INPUT
        self.button.pull = digitalio.Pull.UP

        self._confirmed_state = self.button.value
        self._pending_state = None
        self._stable_count = 0

        self.foundation.startup_print("WifiManagerModule: GP13 initialized. Power-aware AP management active.")

    def get_routes(self):
        return [
            ("/toggle-hotspot-control", self.toggle_hotspot_control),
            ("/get-hotspot-status", self.get_hotspot_status),
            ("/button/state", self.button_state),
        ]

    def register_routes(self, server):
        for route, handler in self.get_routes():
            server.route(route, methods=['POST', 'GET'])(handler)

    def _get_power_state(self):
        if hasattr(self.foundation, "modules"):
            mod_iterable = self.foundation.modules.values() if isinstance(self.foundation.modules, dict) else self.foundation.modules
            for mod in mod_iterable:
                if getattr(mod, "name", "") == "Battery Monitor":
                    return getattr(mod, "power_state", "UNKNOWN")
        return "UNKNOWN"

    def _shut_down_wifi_and_sleep(self):
        self.foundation.startup_print("Initiating Wi-Fi AP shutdown due to battery power timeout...")
        try:
            if wifi.radio.enabled:
                wifi.radio.stop_ap()
                self.foundation.startup_print("Wi-Fi AP shut down.")
            else:
                self.foundation.startup_print("Wi-Fi AP already off.")
        except Exception as e:
            self.foundation.startup_print("Error shutting down AP: {}".format(e))

    def _wake_wifi_ap(self):
        self.foundation.startup_print("Waking Wi-Fi AP...")
        try:
            ssid = os.getenv("WIFI_SSID", "WicdCO2")
            password = os.getenv("WIFI_PASSWORD", "")
            wifi.radio.start_ap(ssid, password)
            self.foundation.startup_print("Wi-Fi AP restarted.")
        except Exception as e:
            self.foundation.startup_print("Error restarting AP: {}".format(e))
            return

        # FIX Bug 2: restore static IP after every AP restart.
        try:
            self.foundation.safe_set_ipv4_address()
            self.foundation.startup_print("Wi-Fi AP static IP restored.")
        except Exception as e:
            self.foundation.startup_print("Error restoring static IP: {}".format(e))

    def update(self):
        now = time.monotonic()

        current_btn = self.button.value
        button_pressed_event = False

        if current_btn != self._confirmed_state:
            if current_btn == self._pending_state:
                self._stable_count += 1
            else:
                self._pending_state = current_btn
                self._stable_count = 1

            if self._stable_count >= self.DEBOUNCE_CYCLES:
                self._confirmed_state = current_btn
                self._pending_state = None
                self._stable_count = 0

                if not self._confirmed_state:
                    self.press_count += 1
                    self.toggle_state = not self.toggle_state
                    button_pressed_event = True
                    self.foundation.startup_print("WifiManager: AP Timer Reset Triggered by button.")  # FIX Bug 4
        else:
            self._pending_state = None
            self._stable_count = 0

        current_power = self._get_power_state()
        if current_power == "USB":
            if not self.timeout_disabled:
                self.timeout_disabled = True
                self.foundation.startup_print("WifiManager: USB Power detected. AP timer suspended.")
            self.user_override_active = False
        elif current_power == "BATTERY":
            if self.timeout_disabled and not self.user_override_active:
                self.timeout_disabled = False
                self.foundation.startup_print("WifiManager: Battery Power detected. AP timer engaged.")

        if button_pressed_event:
            self.last_activity_time = now
            self.user_override_active = False
            if self.ap_is_off_and_logged:
                self._wake_wifi_ap()
                self.ap_is_off_and_logged = False

        if not self.timeout_disabled:
            if wifi.radio.enabled and not self.ap_is_off_and_logged:
                elapsed = now - self.last_activity_time
                if elapsed > self.timeout_seconds:
                    self._shut_down_wifi_and_sleep()
                    self.ap_is_off_and_logged = True
        else:
            if self.ap_is_off_and_logged:
                self._wake_wifi_ap()
                self.ap_is_off_and_logged = False

    def toggle_hotspot_control(self, request: Request):
        self.last_activity_time = time.monotonic()
        current_power = self._get_power_state()

        if current_power == "USB":
            self.timeout_disabled = True
            return Response(request, "USB Power active. Hotspot timer permanently suspended.", content_type="text/plain")

        if not self.timeout_disabled:
            self.timeout_disabled = True
            self.user_override_active = True
            return Response(request, "Automatic timeout disabled. Hotspot will remain open.", content_type="text/plain")
        else:
            self._shut_down_wifi_and_sleep()
            self.ap_is_off_and_logged = True
            self.user_override_active = False
            return Response(request, "Hotspot closed. Power cycle or physical button press required to restart.", content_type="text/plain")

    def get_hotspot_status(self, request: Request):
        # FIX Bug 1: removed erroneous self.last_activity_time = time.monotonic() 
        # that was here before. It caused elapsed to always be ~0.
        now = time.monotonic()
        elapsed = now - self.last_activity_time
        time_remaining = max(0, self.timeout_seconds - elapsed)

        json_bool = "true" if self.timeout_disabled else "false"
        json_str = '{{"timeout_disabled": {}, "time_remaining": {}}}'.format(
            json_bool, int(time_remaining)
        )
        return Response(request, json_str, content_type="application/json")

    def button_state(self, request: Request):
        body = "{}|{}".format("ON" if self.toggle_state else "OFF", self.press_count)
        return Response(request, body, content_type="text/plain")

    def get_dashboard_html(self):
        return """
        <div class="module" id="hotspot-timeout-card">
          <h3>Wi-Fi Hotspot Controls</h3>
          <p id="hotspot-timeout-desc">
            By default, the Wi-Fi hotspot (AP) will shut down after a period of inactivity for security and power saving.
          </p>
          <p id="countdown-container">
            Hotspot will close in: <span id="countdown-display" style="font-weight: bold;">--:--</span>
          </p>
          <button id="hotspot-btn" onclick="toggleHotspotControl()">Loading...</button>
          <div id="hotspot-result"></div>
          
          <hr style="margin-top: 15px; margin-bottom: 15px;">
          
          <h4>Hardware Wake Button</h4>
          <p><strong>State:</strong> <span id="btn-state">--</span></p>
          <p><strong>Press Count:</strong> <span id="btn-count">--</span></p>
        </div>
        <script>
        let countdownInterval = null;
        let currentTimeoutDisabled = null;

        function startCountdown(totalSeconds) {
            if (countdownInterval) {
                clearInterval(countdownInterval);
            }

            let remaining = totalSeconds;
            const display = document.getElementById('countdown-display');

            countdownInterval = setInterval(() => {
                if (remaining <= 0) {
                    clearInterval(countdownInterval);
                    display.textContent = "Closed";
                    return;
                }
                
                remaining--;
                
                const minutes = Math.floor(remaining / 60);
                const seconds = remaining % 60;
                display.textContent = String(minutes).padStart(2, '0') + ":" + String(seconds).padStart(2, '0');

            }, 1000);
        }

        function updateHotspotButtonState() {
            fetch('/get-hotspot-status')
                .then(response => response.json())
                .then(status => {
                    const btn = document.getElementById('hotspot-btn');
                    const countdownContainer = document.getElementById('countdown-container');

                    btn.disabled = false;

                    if (status.timeout_disabled !== currentTimeoutDisabled) {
                        currentTimeoutDisabled = status.timeout_disabled;
                        if (status.timeout_disabled) {
                            btn.textContent = 'Close Hotspot Now';
                            countdownContainer.style.display = 'none';
                            if (countdownInterval) clearInterval(countdownInterval);
                        } else {
                            btn.textContent = 'Keep Hotspot Open';
                            countdownContainer.style.display = 'block';
                            startCountdown(status.time_remaining);
                        }
                    }
                })
                .catch(() => {
                    const btn = document.getElementById('hotspot-btn');
                    btn.textContent = 'Status Unavailable';
                    btn.disabled = true;
                });
        }

        function toggleHotspotControl() {
            const btn = document.getElementById('hotspot-btn');
            const resultEl = document.getElementById('hotspot-result');
            
            if (btn.textContent === 'Close Hotspot Now') {
                if (confirm("Are you sure you want to close the Wi-Fi hotspot? A physical power cycle or button press will be required to restart it.")) {
                    fetchAndHandleToggle(btn, resultEl);
                }
            } else {
                fetchAndHandleToggle(btn, resultEl);
            }
        }

        function fetchAndHandleToggle(btn, resultEl) {
            const isClosing = btn.textContent === 'Close Hotspot Now';
            btn.disabled = true;

            fetch('/toggle-hotspot-control', { method: 'POST' })
                .then(response => response.text())
                .then(result => {
                    resultEl.textContent = result;
                    updateHotspotButtonState();
                    if (result.includes("Hotspot closed")) {
                        btn.disabled = true;
                    } else {
                        btn.disabled = false;
                    }
                })
                .catch(error => {
                    if (isClosing && error.message.includes('Failed to fetch')) {
                        resultEl.textContent = 'Success! Hotspot has been shut down.';
                    } else {
                        resultEl.textContent = 'Error: ' + error.message;
                        btn.disabled = false;
                        updateHotspotButtonState();
                    }
                });
        }

        function pollButtonState() {
            fetch('/button/state')
                .then(r => r.text())
                .then(data => {
                    var parts = data.split('|');
                    var state = parts[0];
                    var el = document.getElementById('btn-state');
                    el.textContent = state;
                    el.style.color = (state === 'ON') ? '#28a745' : '#6c757d';
                    document.getElementById('btn-count').textContent = parts[1] || '0';
                })
                .catch(() => {});
        }

        document.addEventListener('DOMContentLoaded', () => {
            updateHotspotButtonState();
            setInterval(updateHotspotButtonState, 5000);
            pollButtonState();
            setInterval(pollButtonState, 500);
        });
        </script>
        """
