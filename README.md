# WicdCO₂: Open-Source NDIR CO₂ Monitor

The WicdCO₂ is a standalone, low-cost environmental monitor designed for high-precision CO₂ tracking in Controlled Environment Agriculture (CEA) and scientific research. Built on the Wicd Platform, it utilizes the Raspberry Pi Pico 2 W (RP2350) and the Sensirion SCD30 Dual-Channel NDIR sensor. The device operates an isolated Wi-Fi Basic Service Set, serving a browser-based Virtual Control Panel (VCP) for real-time visualization, hardware configuration, and CSV data retrieval without requiring institutional IT infrastructure.

## Repository Structure

* **/firmware**: Contains the CircuitPython 9.x `code.py` script, the `settings.toml` network configuration file, and the required operational subset of the Wicd Framework engine.


* **/mechanical**: 3D-printable enclosure files (STL and STEP) optimized for SCD30 dimensions and natural CO₂ dispersion via baffled vent holes.


* **/electrical**: Fritzing wiring diagrams and layout schematics detailing the I2C hardware backplane connections.



## Bill of Materials (Core Components)

* **Microcontroller:** Raspberry Pi Pico 2 W


* **Datalogger:** Adafruit PiCowbell Adalogger (provides battery-backed Real-Time Clock and microSD storage)


* **Backplane:** Adafruit Proto Doubler PiCowbell


* **Sensor Element:** Sensirion SCD30 NDIR Module


* **Connection:** JST-SH 4-pin Cable (Qwiic/Stemma QT)



## Firmware Deployment

The WicdCO₂ utilizes a manual, library-flattening deployment approach to comply with the flat-file constraints of the CircuitPython runtime environment.

1. Flash the Raspberry Pi Pico 2 W with the CircuitPython 9.x `.uf2` binary.


2. Clone or download this repository.
3. Copy the contents of the `/firmware` directory directly to the root of the mounted `CIRCUITPY` mass storage volume.


4. Open the `settings.toml` file located in the `CIRCUITPY` root directory to define the network credentials (`CIRCUITPY_WIFI_SSID`, `CIRCUITPY_WIFI_PASSWORD`) and baseline logging interval.



## Operation and VCP Access

1. **Initialize Power:** Apply power via the primary USB connection.
2. **Network Connection:** Connect a client device to the broadcasted access point using the credentials defined in `settings.toml` (Default fallback SSID: `PicoTest-Node00`, Password: `testpass123`).


3. **Launch VCP:** Navigate a standard web browser to the static IP address **[http://192.168.4.1](https://www.google.com/search?q=http://192.168.4.1)**.


4. **Data Management:** Utilize the VCP to synchronize the hardware clock (Sync to Browser Time), manage logging intervals, and download historical CSV files remotely via the SD Manager.



## Fail-Safe Configuration Recovery

If the device becomes inaccessible due to credential configuration errors, execute the hardware-absent fail-safe mechanism:

1. Disconnect the primary power supply.


2. Physically extract the microSD card from the Adalogger.


3. Apply power without the SD card inserted. The firmware will bypass custom parameters and broadcast the Tier 2 factory-default Basic Service Set.


4. Mount the SD card on a workstation to correct or delete the corrupted `settings.toml` file.


5. Remove power, reinsert the SD card, and initialize a standard boot sequence.



## Licenses

* **Software/Firmware:** MIT License


* **Hardware/Mechanical:** CERN-OHL-S
