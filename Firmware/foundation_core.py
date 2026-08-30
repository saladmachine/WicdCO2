# foundation_core.py
import wifi
import socketpool
import ipaddress
import time
import os
import microcontroller
from adafruit_httpserver import Server, Request, Response
import gc
from foundation_templates import TemplateSystem
import board
import busio

class Config:
    WIFI_SSID = "Wicdpico"
    WIFI_PASSWORD = "simpletest"
    WIFI_MODE = "AP"
    WIFI_AP_TIMEOUT_MINUTES = 10
    BLINK_INTERVAL = 0.25
    TIMEZONE_OFFSET_HOURS = 0 # Default to UTC
    WICDPICO_VERSION = "0.0.0" # Default version
    SYSTEM_NAME = "WicdPico Dashboard" # Default system name
    ACTIVE_SENSOR = "SCD30" # Default sensor
    PRIMARY_SENSOR_KEY = "sensor" # Default target sensor key

class WicdpicoFoundation:
    def __init__(self):
        self.config = Config()
        self.startup_log = []
        self.server = None
        self.modules = {}
        self.module_order = []
        self.config_failed = False
        self.wifi_mode = "AP"
        self.templates = TemplateSystem()
        self.server_ip = None
        self.poll_error_logged = False
        
class WicdHardwareConfig:
    """
    Configuration object for hardware pinouts.
    Allows WicdPico to be ported to different boards without modifying core code.
    Defaults are for Raspberry Pi Pico 2 W.
    """
    def __init__(self, i2c_scl=None, i2c_sda=None):
        # Default to Pico W pins if not specified
        self.i2c_scl = i2c_scl if i2c_scl else board.GP5
        self.i2c_sda = i2c_sda if i2c_sda else board.GP4

class WicdpicoFoundation:
    def __init__(self, hardware_config=None):
        self.config = Config()
        self.startup_log = []
        self.server = None
        self.modules = {}
        self.module_order = []
        self.config_failed = False
        self.wifi_mode = "AP"
        self.templates = TemplateSystem()
        self.server_ip = None
        self.poll_error_logged = False
        self.alerts = [] # List of alert messages to display in dashboard
        
        # Use provided config or create default
        if hardware_config is None:
            self.hw_config = WicdHardwareConfig()
        else:
            self.hw_config = hardware_config

        # Initialize self.i2c defensively
        self.i2c = None 
        
        try:
            self.i2c = busio.I2C(self.hw_config.i2c_scl, self.hw_config.i2c_sda)
            self.startup_print("✓ I2C Bus initialized on {}/{}.".format(self.hw_config.i2c_scl, self.hw_config.i2c_sda))
        except RuntimeError as e:
            # Catch RuntimeError for the "No pull up" error (Adafruit standard)
            self.startup_print("✗ FAILED to initialize I2C bus: {} (Attribute self.i2c set to None).".format(e))
        except Exception as e:
            # Catch any other exception during I2C setup
            self.startup_print("✗ FAILED to initialize I2C bus: {} (Attribute self.i2c set to None).".format(e))

    def load_user_config(self):
        """
        Dual-tier config loading.
        Tier 1: settings.toml on CIRCUITPY USB drive (network credentials).
        Tier 2: /sd/SD_Override.toml on SD card (ACTIVE_SENSOR, SYSTEM_NAME, etc).
        The SD override is ALWAYS applied on top of Tier 1, never skipped.
        """
        # --- Tier 1: Load base config from CIRCUITPY settings.toml ---
        try:
            self.startup_print("Loading Tier 1 config (settings.toml)...")
            toml_ssid = os.getenv("WIFI_SSID")
            toml_password = os.getenv("WIFI_PASSWORD")
            toml_timeout = os.getenv("WIFI_AP_TIMEOUT_MINUTES")
            toml_blink = os.getenv("BLINK_INTERVAL")
            toml_tz_offset = os.getenv("TIMEZONE_OFFSET_HOURS")
            toml_version = os.getenv("WICDPICO_VERSION")
            toml_system_name = os.getenv("SYSTEM_NAME")
            toml_primary_sensor = os.getenv("PRIMARY_SENSOR_KEY")

            if toml_ssid and toml_password:
                self.startup_print("Found settings.toml, applying base config.")
                self.config.WIFI_MODE = "AP"
                self.config.WIFI_SSID = self.decode_html_entities(str(toml_ssid))
                self.config.WIFI_PASSWORD = self.decode_html_entities(str(toml_password))
                if toml_timeout: self.config.WIFI_AP_TIMEOUT_MINUTES = int(toml_timeout)
                if toml_blink: self.config.BLINK_INTERVAL = float(toml_blink)
                if toml_tz_offset: self.config.TIMEZONE_OFFSET_HOURS = int(toml_tz_offset)
                if toml_version: self.config.WICDPICO_VERSION = str(toml_version)
                if toml_system_name: self.config.SYSTEM_NAME = str(toml_system_name)
                if toml_primary_sensor: self.config.PRIMARY_SENSOR_KEY = str(toml_primary_sensor)
            else:
                self.startup_print("No settings.toml found, trying config.py fallback.")
                try:
                    import config as user_config
                    self.config.WIFI_SSID = self.decode_html_entities(str(user_config.WIFI_SSID))
                    self.config.WIFI_PASSWORD = self.decode_html_entities(str(user_config.WIFI_PASSWORD))
                    if hasattr(user_config, 'WIFI_AP_TIMEOUT_MINUTES'):
                        self.config.WIFI_AP_TIMEOUT_MINUTES = int(user_config.WIFI_AP_TIMEOUT_MINUTES)
                    if hasattr(user_config, 'BLINK_INTERVAL'):
                        self.config.BLINK_INTERVAL = float(user_config.BLINK_INTERVAL)
                    if hasattr(user_config, 'TIMEZONE_OFFSET_HOURS'):
                        self.config.TIMEZONE_OFFSET_HOURS = int(user_config.TIMEZONE_OFFSET_HOURS)
                    if hasattr(user_config, 'WICDPICO_VERSION'):
                        self.config.WICDPICO_VERSION = str(user_config.WICDPICO_VERSION)
                except Exception as e:
                    self.startup_print("config.py fallback failed: {}. Using emergency defaults.".format(e))
                    self.config_failed = True
                    self.config.WIFI_SSID = "Wicdpico-Recovery"
                    self.config.WIFI_PASSWORD = "emergency123"

        except Exception as e:
            self.startup_print("Tier 1 config load failed: {}. Using emergency defaults.".format(e))
            self.config_failed = True
            self.config.WIFI_MODE = "AP"
            self.config.WIFI_SSID = "Wicdpico-Recovery"
            self.config.WIFI_PASSWORD = "emergency123"
            self.config.BLINK_INTERVAL = 0.10

        # --- Tier 2: ALWAYS apply SD_Override.toml on top of Tier 1 ---
        # This is the primary authority for ACTIVE_SENSOR and dashboard settings.
        sd_override_path = "/sd/SD_Override.toml"
        try:
            os.stat(sd_override_path)
            self.startup_print("Found SD override at {}. Applying...".format(sd_override_path))
            with open(sd_override_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key == "WIFI_SSID": self.config.WIFI_SSID = self.decode_html_entities(val)
                        elif key == "WIFI_PASSWORD": self.config.WIFI_PASSWORD = self.decode_html_entities(val)
                        elif key == "SYSTEM_NAME": self.config.SYSTEM_NAME = val
                        elif key == "TIMEZONE_OFFSET_HOURS": self.config.TIMEZONE_OFFSET_HOURS = int(val)
                        elif key == "ACTIVE_SENSOR": self.config.ACTIVE_SENSOR = val.upper()
                        elif key == "PRIMARY_SENSOR_KEY": self.config.PRIMARY_SENSOR_KEY = val
            self.startup_print("SD_Override.toml applied. Active sensor: {}".format(self.config.ACTIVE_SENSOR))
        except OSError:
            # No SD override file - this is normal. Defaults stand.
            self.startup_print("No SD_Override.toml found. Using Tier 1 defaults.")
        except Exception as e:
            self.startup_print("ERROR: Corrupt SD_Override.toml: {}".format(e))
            self.add_alert("Warning: SD_Override.toml is corrupt. Using Safe Defaults.")
    
    def startup_print(self, message):
        print(message)
        self.startup_log.append(message)

    def add_alert(self, message):
        """Add a persistent alert message to be shown on the Dashboard."""
        if message not in self.alerts:
            self.alerts.append(message)

    def decode_html_entities(self, text):
        text = text.replace('&quot;', '"')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&#39;', "'")
        return text

    def validate_wifi_password(self, password):
        if not password:
            return False, "WiFi password cannot be empty"
        if len(password) < 8:
            return False, "WiFi password must be at least 8 characters"
        if len(password) > 64:
            return False, "WiFi password cannot exceed 64 characters"
        return True, ""

    def get_module(self, name):
        return self.modules.get(name)

    def safe_start_access_point(self, ssid, password):
        is_valid, error_msg = self.validate_wifi_password(password)
        if not is_valid:
            self.startup_print("Password validation failed: {}".format(error_msg))
            self.startup_print("Falling back to default credentials")
            ssid = "Wicdpico-Recovery"
            password = "emergency123"

        try:
            self.startup_print("Starting AP with SSID: {}".format(ssid))
            wifi.radio.start_ap(ssid=ssid, password=password)
            self.startup_print("AP started successfully")
            return True, ssid, password
        except Exception as e:
            self.startup_print("AP start failed: {}".format(e))
            try:
                wifi.radio.start_ap(ssid="Wicdpico-Recovery", password="emergency123")
                self.startup_print("AP started with emergency defaults")
                return False, "Wicdpico-Recovery", "emergency123"
            except Exception as e2:
                self.startup_print("AP start failed completely: {}".format(e2))
                return False, ssid, password

    def safe_set_ipv4_address(self):
        if self.wifi_mode != "AP":
            return True
            
        try:
            time.sleep(0.5)
            wifi.radio.set_ipv4_address_ap(
                ipv4=ipaddress.IPv4Address("192.168.4.1"),
                netmask=ipaddress.IPv4Address("255.255.255.0"),
                gateway=ipaddress.IPv4Address("192.168.4.1")
            )
            self.startup_print("IPv4 configured successfully")
            return True
        except Exception as e:
            self.startup_print("IPv4 config failed: {}".format(e))
            return False

    def initialize_network(self):
        self.load_user_config()
        self.wifi_mode = "AP"
        self.startup_print("WiFi mode: AP (standalone sensor meter)")
        
        ap_success, ssid, password = self.safe_start_access_point(
            self.config.WIFI_SSID,
            self.config.WIFI_PASSWORD
        )
        self.config.WIFI_SSID = ssid
        self.config.WIFI_PASSWORD = password

        ipv4_success = self.safe_set_ipv4_address()
        pool = socketpool.SocketPool(wifi.radio)
        self.server = Server(pool, "/", debug=False)
        return ap_success and ipv4_success

    def register_module(self, name, module):
        self.modules[name] = module
        self.module_order.append(name) # NEW: Record the registration order
        if hasattr(module, 'register_routes'):
            module.register_routes(self.server)

    def start_server(self):
        @self.server.route("/", methods=['GET'])
        def root_route(request: Request):
            no_cache_headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
            try:
                html_content = self.render_dashboard()
                return Response(request, html_content, content_type="text/html", headers=no_cache_headers)
            except Exception as e:
                self.startup_print("Error rendering dashboard: {}".format(e))
                return Response(request, "<h1>Error</h1><p>Could not render dashboard.</p>", content_type="text/html", headers=no_cache_headers)

        self.server_ip = "192.168.4.1"
        self.server.start(self.server_ip, port=80)
        self.startup_print("Foundation ready at http://{}".format(self.server_ip))

    def poll(self):
        try:
            if wifi.radio.enabled and self.server:
                self.server.poll()
            for module in self.modules.values():
                if hasattr(module, 'update'):
                    module.update()
        except Exception as e:
            if not self.poll_error_logged:
                self.startup_print("Error in poll cycle: {}".format(e))
                self.poll_error_logged = True

    def run_main_loop(self):
        while True:
            self.poll()
            time.sleep(0.1)
            gc.collect()

    def render_dashboard(self, title=None):
        if title is None:
            # Use configurable Name AND Version in the title
            title = "{} v{}".format(self.config.SYSTEM_NAME, self.config.WICDPICO_VERSION)

        modules_html = ""
        # MODIFIED: Loop over the ordered list instead of the dictionary
        for name in self.module_order:
            module = self.modules[name]
            try:
                if hasattr(module, 'get_dashboard_html'):
                    module_html = module.get_dashboard_html()
                    if module_html:
                        modules_html += module_html
            except Exception as e:
                modules_html += '<div class="module"><h3>{}</h3><p>Error loading module: {}</p></div>\n'.format(name, e)

        system_info = """
            <p><strong>Sensor Meter:</strong> Standalone AP Mode</p>
            <p><strong>WiFi Hotspot:</strong> {}</p>
            <p><strong>Access URL:</strong> http://192.168.4.1</p>
            <p><strong>Modules loaded:</strong> {}</p>
            <p><strong>System status:</strong> {}</p>
        """.format(self.config.WIFI_SSID, len(self.modules), 'Configuration Error' if self.config_failed else 'Ready')
        return self.templates.render_page(title, modules_html, system_info, alerts=self.alerts)