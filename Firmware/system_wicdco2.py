# system_wicdco2.py
# SPDX-FileCopyrightText: 2025
# SPDX-License-Identifier: MIT

"""
WicdCO2 System Entry Point
==========================
Orchestrates the WicdCO2 air quality monitor application.
Composes the Foundation with SCD30 and other modules.
"""

import time
import board
from foundation_core import WicdpicoFoundation, WicdHardwareConfig

from module_scd30 import SCD30Module
from module_SD_manager import SDManagerModule
from module_rtc import RTCModule
from module_datalogger import DataloggerModule
from module_live_chart import LiveChartModule
from module_settings import SettingsModule


def main():
    print("--- WicdCO2 System Starting ---")
    
    # 1. Initialize Foundation (and shared hardware resources)
    # Using default hardware config (Pico 2 W standard)
    hw_config = WicdHardwareConfig() 
    foundation = WicdpicoFoundation(hw_config)
    
    # SD Card Manager (Initialize EARLY so config can be read from SD)
    sd_manager = SDManagerModule(foundation)

    # 2.Initialize Network
    # This loads settings.toml (potentially from SD), starts AP, and sets up the server
    if not foundation.initialize_network():
        print("CRITICAL: Network initialization failed.")
        # We continue anyway to at least try to log data or show error on local display if one existed
    
    # 3. Instantiate Modules
    # Pass the foundation (which holds the shared I2C bus)
    
    # SCD30 (Primary CO2/Temp/Humidity Sensor)
    # The foundation initializes the I2C bus on foundation.i2c
    scd30 = SCD30Module(foundation.i2c)
        
    # RTC Clock (Heartbeat)
    rtc = RTCModule(foundation)
    
    # Data Logger (Logic)
    logger = DataloggerModule(foundation)
    
    # Live Chart (Zero-risk visualizer)
    live_chart = LiveChartModule()
    
    # Settings (Headless Config)
    settings = SettingsModule(foundation)

    # 4. Register Modules with Foundation
    # The order here determines the order on the dashboard
    foundation.register_module("scd30", scd30)
    foundation.register_module("live_chart", live_chart)
    foundation.register_module("rtc", rtc) 
    foundation.register_module("logger", logger) 
    foundation.register_module("sd_manager", sd_manager)
    foundation.register_module("settings", settings) # Keep settings last
        
    # 5. Start Server
    foundation.start_server()
    
    # 6. Enter Main Loop
    print("--- WicdCO2 System Running ---")
    foundation.run_main_loop()

main()