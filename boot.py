# boot.py -- Executed on boot (including wake-boot from deepsleep)
import gc
import json
import machine
import network
import time

# Enable garbage collection
gc.enable()

# --- CONFIGURATION & STORAGE ---
CONFIG_FILE = "wifi_config.json"

DEFAULT_WIFI_SSID = "YOUR_WIFI_SSID"
DEFAULT_WIFI_PASS = "YOUR_WIFI_PASSWORD_HERE"

AP_SSID = "Lacerta"
AP_PASS = "12345678"  # Minimum 8 characters


def load_wifi_credentials():
    """Loads saved Wi-Fi credentials from flash memory, or returns defaults."""
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            return data.get("ssid", DEFAULT_WIFI_SSID), data.get(
                "pass", DEFAULT_WIFI_PASS
            )
    except Exception:
        return DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASS


def setup_networking():
    """Manages dual-mode Wi-Fi setup (STA mode with fallback to Access Point)."""
    ssid, password = load_wifi_credentials()

    wlan_sta = network.WLAN(network.STA_IF)
    wlan_sta.active(True)

    print(f"Attempting connection to Wi-Fi network: {ssid}...")
    try:
        wlan_sta.connect(ssid, password)
    except Exception as e:
        print(f"Wi-Fi connect attempt error: {e}")

    # Wait up to 10 seconds for connection
    for _ in range(20):
        if wlan_sta.isconnected():
            ip = wlan_sta.ifconfig()[0]
            print(f"Connected to Wi-Fi network successfully! IP: {ip}")
            return ip
        time.sleep(0.5)

    # Fallback to Access Point if station mode fails
    print(
        f"Could not connect to '{ssid}'. Activating Access Point: '{AP_SSID}'..."
    )
    wlan_sta.active(False)  # Turn off station mode to clean up state

    wlan_ap = network.WLAN(network.AP_IF)
    wlan_ap.active(True)
    wlan_ap.config(
        essid=AP_SSID, password=AP_PASS, authmode=network.AUTH_WPA_WPA2_PSK
    )

    ip = wlan_ap.ifconfig()[0]
    print(f"Hotspot operational. Connect to '{AP_SSID}' via IP: {ip}")
    return ip


# Execute network initialization on boot
ip_address = setup_networking()
