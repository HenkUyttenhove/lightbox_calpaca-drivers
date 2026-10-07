# main.py -- Executed after boot.py
import json
import machine
import network
import uasyncio as asyncio

CONFIG_FILE = "wifi_config.json"

PWM_PIN = 12  # Hardware PWM GPIO pin
PWM_FREQ = 25000  # 25kHz prevents camera shutter banding/flicker

# --- GLOBAL DEVICE STATE ---
device_state = {
    "brightness": 0,  # 0 to 1023 (10-bit PWM)
    "calibratorstate": 4,  # 0=NotReady, 1=Ready, 2=Calibrating, 3=Failed, 4=Off
    "coverstate": 0,  # 0=NotPresent
    "connected": False,
}

# --- HARDWARE SETUP ---
pwm_gate = machine.PWM(machine.Pin(PWM_PIN), freq=PWM_FREQ, duty=0)


def save_wifi_credentials(ssid, password):
    """Saves new Wi-Fi credentials to flash memory."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"ssid": ssid, "pass": password}, f)
        print("[DEBUG] Wi-Fi configuration saved successfully.")
    except Exception as e:
        print(f"[DEBUG] Error saving Wi-Fi configuration: {e}")


def unquote(string):
    """Percent-decoding helper for standard web form submissions."""
    parts = string.split("%")
    res = parts[0]
    for part in parts[1:]:
        if len(part) >= 2:
            try:
                res += chr(int(part[:2], 16)) + part[2:]
            except ValueError:
                res += "%" + part
        else:
            res += "%" + part
    return res


def parse_query_or_body(data_str):
    """Utility to parse key-value pairs from URL query strings or form payloads."""
    params = {}
    if not data_str:
        return params

    data_str = data_str.replace("+", " ")
    pairs = data_str.split("&")
    for pair in pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            k = unquote(k.strip().lower())
            v = unquote(v.strip())
            params[k] = v
    return params


def build_alpaca_response(
    client_id, transaction_id, value=None, error_num=0, error_msg=""
):
    """Formats standard JSON matching the ASCOM Alpaca API definition."""
    resp = {
        "ClientTransactionID": int(client_id) if client_id else 0,
        "ServerTransactionID": int(transaction_id) if transaction_id else 1,
        "ErrorNumber": error_num,
        "ErrorMessage": error_msg,
    }
    if value is not None:
        resp["Value"] = value
    return resp


def update_pwm_brightness(new_brightness):
    """Safely updates duty cycle and internal device state."""
    new_brightness = max(0, min(1023, int(new_brightness)))
    device_state["brightness"] = new_brightness
    pwm_gate.duty(new_brightness)

    if new_brightness > 0:
        device_state["calibratorstate"] = 1  # Ready / Emitting
    else:
        device_state["calibratorstate"] = 4  # Off


async def safe_close_writer(writer):
    """Safely closes standard MicroPython uasyncio StreamWriters."""
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


# --- WEB MANAGEMENT DASHBOARD (PORT 80) ---
def render_web_page(msg=""):
    """Generates simple HTML UI for Port 80."""
    brightness = device_state["brightness"]
    pct = round((brightness / 1023) * 100, 1)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Lacerta Lightbox Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #121212; color: #e0e0e0; }}
        .card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; max-width: 400px; margin: 0 auto 20px auto; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        h2 {{ color: #4fc3f7; margin-top: 0; }}
        label {{ display: block; margin-top: 10px; font-weight: bold; }}
        input[type=text], input[type=password], input[type=number] {{ width: 100%; padding: 8px; margin-top: 5px; box-sizing: border-box; background: #2e2e2e; color: #fff; border: 1px solid #444; border-radius: 4px; }}
        input[type=submit] {{ background: #0288d1; color: white; border: none; padding: 10px; width: 100%; margin-top: 15px; border-radius: 4px; font-size: 16px; cursor: pointer; }}
        input[type=submit]:hover {{ background: #039be5; }}
        .status {{ font-size: 1.2em; font-weight: bold; color: #81c784; }}
        .alert {{ color: #ffb74d; font-style: italic; margin-bottom: 15px; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Lacerta Lightbox</h2>
        <p>Current PWM Duty: <span class="status">{brightness} / 1023 ({pct}%)</span></p>
        
        <form action="/" method="POST">
            <label for="pwm">Set PWM (0 - 1023):</label>
            <input type="number" id="pwm" name="pwm" min="0" max="1023" value="{brightness}">
            <input type="submit" value="Update Brightness">
        </form>
    </div>

    <div class="card">
        <h2>Wi-Fi Settings</h2>
        {f'<p class="alert">{msg}</p>' if msg else ''}
        <form action="/save_wifi" method="POST">
            <label for="ssid">Network SSID:</label>
            <input type="text" id="ssid" name="ssid" placeholder="Enter Wi-Fi SSID" required>
            
            <label for="pass">Password:</label>
            <input type="password" id="pass" name="pass" placeholder="Enter Wi-Fi Password">
            
            <input type="submit" value="Save & Reboot ESP32">
        </form>
    </div>
</body>
</html>"""
    return html


async def handle_http_client(reader, writer):
    """Handles Port 80 browser interface requests."""
    try:
        request_line = await reader.readline()
        if not request_line:
            return

        req_str = request_line.decode("utf-8")
        parts = req_str.split(" ")
        if len(parts) < 2:
            return
        method, url = parts[0], parts[1]

        content_length = 0
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            line_str = line.decode("utf-8").lower()
            if line_str.startswith("content-length:"):
                content_length = int(line_str.split(":")[1].strip())

        body_data = ""
        if method == "POST" and content_length > 0:
            body = await reader.read(content_length)
            body_data = body.decode("utf-8")

        params = parse_query_or_body(body_data)

        if url == "/save_wifi" and method == "POST":
            new_ssid = params.get("ssid", "")
            new_pass = params.get("pass", "")

            if new_ssid:
                save_wifi_credentials(new_ssid, new_pass)
                response_html = render_web_page(
                    f"Saved settings for '{new_ssid}'. Rebooting ESP32..."
                )
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
                )
                writer.write(response_html.encode("utf-8"))
                await writer.drain()
                await safe_close_writer(writer)

                await asyncio.sleep(2)
                machine.reset()
                return

        elif url == "/" and method == "POST":
            if "pwm" in params:
                update_pwm_brightness(params["pwm"])

        response_html = render_web_page()
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
        )
        writer.write(response_html.encode("utf-8"))
        await writer.drain()

    except Exception as e:
        print(f"[DEBUG] HTTP Server Exception: {e}")
    finally:
        await safe_close_writer(writer)


# --- ASCOM ALPACA SERVER (PORT 11111) ---
async def handle_alpaca_client(reader, writer):
    """Handles ASCOM Alpaca Protocol REST endpoints."""
    try:
        request_line = await reader.readline()
        if not request_line:
            return

        req_str = request_line.decode("utf-8")
        parts = req_str.split(" ")
        if len(parts) < 2:
            return
        method, url = parts[0], parts[1]

        print(f"[ALPACA DEBUG] Incoming Request: {method} {url}")

        url_path = url
        query_string = ""
        if "?" in url:
            url_path, query_string = url.split("?", 1)

        content_length = 0
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            line_str = line.decode("utf-8").lower()
            if line_str.startswith("content-length:"):
                content_length = int(line_str.split(":")[1].strip())

        body_data = ""
        if content_length > 0:
            body = await reader.read(content_length)
            body_data = body.decode("utf-8")

        # Combine parameters from both query string and body
        params = parse_query_or_body(query_string)
        params.update(parse_query_or_body(body_data))

        client_id = params.get("clienttransactionid", 0)
        trans_id = params.get("servertransactionid", 42)

        print(f"[ALPACA DEBUG] Parameters Parsed: {params}")

        url_lower = url_path.lower()

        # Handle Connected property
        if "covercalibrator/0/connected" in url_lower:
            if method == "GET":
                value = device_state["connected"]
                print(f"[ALPACA DEBUG] ASCOM Checking Connected status -> {value}")
                data = build_alpaca_response(client_id, trans_id, value=value)
            elif method == "PUT":
                conn_val = params.get("connected", "false").lower() == "true"
                device_state["connected"] = conn_val
                print(f"[ALPACA DEBUG] ASCOM Set Connected -> {conn_val}")
                data = build_alpaca_response(client_id, trans_id)

        # Handle Standard ASCOM CoverCalibrator Methods & Attributes
        elif "covercalibrator/0/brightness" in url_lower:
            if method == "GET":
                print(
                    f"[ALPACA DEBUG] Getting Brightness: {device_state['brightness']}"
                )
                data = build_alpaca_response(
                    client_id, trans_id, value=device_state["brightness"]
                )
            else:
                new_brightness = params.get("brightness", 0)
                print(f"[ALPACA DEBUG] Setting Brightness: {new_brightness}")
                update_pwm_brightness(new_brightness)
                data = build_alpaca_response(client_id, trans_id)

        elif "covercalibrator/0/calibratorstate" in url_lower:
            print(
                f"[ALPACA DEBUG] Getting CalibratorState: {device_state['calibratorstate']}"
            )
            data = build_alpaca_response(
                client_id, trans_id, value=device_state["calibratorstate"]
            )

        elif "covercalibrator/0/coverstate" in url_lower:
            print(
                f"[ALPACA DEBUG] Getting CoverState: {device_state['coverstate']}"
            )
            data = build_alpaca_response(
                client_id, trans_id, value=device_state["coverstate"]
            )

        elif "covercalibrator/0/calibratoroff" in url_lower and method == "PUT":
            print("[ALPACA DEBUG] CalibratorOff command received.")
            update_pwm_brightness(0)
            data = build_alpaca_response(client_id, trans_id)

        elif "covercalibrator/0/calibratoron" in url_lower and method == "PUT":
            brightness_target = int(params.get("brightness", 512))
            print(
                f"[ALPACA DEBUG] CalibratorOn command received. Brightness: {brightness_target}"
            )
            update_pwm_brightness(brightness_target)
            data = build_alpaca_response(client_id, trans_id)

        elif "covercalibrator/0/maxbrightness" in url_lower:
            print("[ALPACA DEBUG] Querying MaxBrightness (1023)")
            data = build_alpaca_response(client_id, trans_id, value=1023)

        elif "covercalibrator/0/interfaceversion" in url_lower:
            print("[ALPACA DEBUG] Querying InterfaceVersion (1)")
            data = build_alpaca_response(client_id, trans_id, value=1)

        elif "covercalibrator/0/driverinfo" in url_lower:
            print("[ALPACA DEBUG] Querying DriverInfo")
            data = build_alpaca_response(
                client_id, trans_id, value="MicroPython ESP32 Lacerta CoverCalibrator"
            )

        elif "covercalibrator/0/driverversion" in url_lower:
            print("[ALPACA DEBUG] Querying DriverVersion")
            data = build_alpaca_response(client_id, trans_id, value="1.0")

        elif "covercalibrator/0/name" in url_lower:
            print("[ALPACA DEBUG] Querying Name")
            data = build_alpaca_response(
                client_id, trans_id, value="Lacerta Lightbox"
            )

        elif "covercalibrator/0/description" in url_lower:
            print("[ALPACA DEBUG] Querying Description")
            data = build_alpaca_response(
                client_id, trans_id, value="ESP32 Wireless Flat Panel"
            )

        elif "management/v1/configureddevices" in url_lower:
            print("[ALPACA DEBUG] ASCOM Configured Devices Discovery query")
            devices = [
                {
                    "DeviceName": "Lacerta Wireless Flat Panel",
                    "DeviceType": "CoverCalibrator",
                    "DeviceNumber": 0,
                    "UniqueID": "9C2A4D8B-ESP32-ALPACA-LACERTA-0001",
                }
            ]
            data = build_alpaca_response(client_id, trans_id, value=devices)

        else:
            print(f"[ALPACA DEBUG] Generic response for path: {url_path}")
            data = build_alpaca_response(client_id, trans_id)

        payload = json.dumps(data).encode("utf-8")
        headers = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("utf-8")

        writer.write(headers)
        writer.write(payload)
        await writer.drain()
        print("[ALPACA DEBUG] Response sent successfully.")

    except Exception as e:
        print(f"[ALPACA DEBUG] Alpaca Exception: {e}")
    finally:
        await safe_close_writer(writer)


# --- ASYNC MAIN EVENT LOOP ---
async def main():
    print("Starting Web Dashboard on port 80...")
    print("Starting ASCOM Alpaca Server on port 11111...")

    server_http = await asyncio.start_server(handle_http_client, "0.0.0.0", 80)
    server_alpaca = await asyncio.start_server(
        handle_alpaca_client, "0.0.0.0", 11111
    )

    async with server_http, server_alpaca:
        while True:
            await asyncio.sleep(3600)


# Run main event loop
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Engine safely shut down.")