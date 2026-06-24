import time
import requests
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont

# 1. Hardware Setup (Using your discovered 0x3C address)
serial = i2c(port=1, address=0x3C)
device = ssd1306(serial, width=128, height=64)

# Friendly display names for TfL special-case destination values
DESTINATION_OVERRIDES = {
    "check front of train": "Chk Front",
    "": "Unknown",
}

# 2. TfL API Configuration (Example setup for Watford Station)
STATION_ID = "940GZZLUWAF" 
API_KEY = ""
API_URL = f"https://api.tfl.gov.uk/StopPoint/{STATION_ID}/Arrivals?app_key={API_KEY}"
# If you have an API key, append it like this: f"https://api.tfl.gov.uk/StopPoint/{STATION_ID}/Arrivals?app_key=YOUR_KEY"

def clean_destination(raw_name):
    """Normalise a TfL destinationName for display."""
    cleaned = (raw_name or "").replace("Underground Station", "").strip()
    # Apply friendly overrides for special TfL values (e.g. "Check Front of Train")
    return DESTINATION_OVERRIDES.get(cleaned.lower(), cleaned)

def get_departures():
    try:
        response = requests.get(API_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            met_trains = [train for train in data if train.get("lineName", "").lower() == "metropolitan"]
            sorted_trains = sorted(met_trains, key=lambda x: x.get("timeToStation", 0))
            
            departures = []
            # On a 128x64 screen with larger fonts, 3 trains fit perfectly
            for train in sorted_trains[:3]:
                destination = clean_destination(train.get("destinationName", ""))
                minutes = train.get("timeToStation", 0) // 60
                time_str = "Due" if minutes == 0 else f"{minutes}m"
                
                # Truncate long names to leave room for dots and time
                short_dest = destination[:10].strip()
                departures.append((short_dest, time_str))
            return departures
        else:
            return [("API Error", "")]
    except Exception as e:
        return [("Conn Error", "")]

def update_display():
    # Use a crisp, fixed-width font to make dot padding incredibly predictable
    try:
        # Monospace fonts ensure every character (including dots) uses the exact same width
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
    except IOError:
        font = ImageFont.load_default()
    
    while True:
        train_data = get_departures()
        
        with canvas(device) as draw:
            # 1. Top Border/Header Area
            draw.text((2, 0), "METROPOLITAN DEPARTS", fill="white", font=font)
            draw.line((0, 14, 128, 14), fill="white")
            
            # 2. Main Body with dynamic dot calculations
            y_offset = 18
            if not train_data:
                draw.text((2, y_offset), "No departures", fill="white", font=font)
            else:
                for dest, t_left in train_data:
                    # Target total characters per line to fill a 128px width using this font size
                    # For DejaVuSansMono at 11pt, roughly 19-21 characters fit the screen width.
                    max_chars = 20 
                    
                    # Calculate how many dots we need to pad the middle
                    dots_needed = max_chars - (len(dest) + len(t_left))
                    if dots_needed < 1:
                        dots_needed = 1
                    
                    # Combine them into a single edge-to-edge string
                    full_line_str = f"{dest}{'.' * dots_needed}{t_left}"
                    
                    # Draw the completed full-width line
                    draw.text((2, y_offset), full_line_str, fill="white", font=font)
                    
                    # Move down to the next train slot
                    y_offset += 15
                    
        time.sleep(60)

if __name__ == "__main__":
    update_display()