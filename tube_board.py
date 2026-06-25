import datetime
import math
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
LINE_ID = "metropolitan"
API_KEY = ""
ARRIVALS_URL = f"https://api.tfl.gov.uk/StopPoint/{STATION_ID}/Arrivals?app_key={API_KEY}"
TIMETABLE_URL = f"https://api.tfl.gov.uk/Line/{LINE_ID}/Timetable/{STATION_ID}?app_key={API_KEY}"

# Timetable cache — refreshed every 30 minutes
_timetable_cache = []
_timetable_fetched_at = None
TIMETABLE_TTL = 1800  # seconds

def clean_destination(raw_name):
    """Normalise a TfL destinationName for display."""
    cleaned = (raw_name or "").replace("Underground Station", "").strip()
    return DESTINATION_OVERRIDES.get(cleaned.lower(), cleaned)

def get_timetable():
    """Return cached list of (departure datetime, destination str) from today's timetable."""
    global _timetable_cache, _timetable_fetched_at
    now = datetime.datetime.now()

    # Return cache if still fresh
    if _timetable_fetched_at and (now - _timetable_fetched_at).total_seconds() < TIMETABLE_TTL:
        return _timetable_cache

    try:
        response = requests.get(TIMETABLE_URL, timeout=10)
        if response.status_code != 200:
            return _timetable_cache  # keep stale cache on error
        data = response.json()

        # Build a map of stopId -> friendly name from the stops list
        stops = {s["id"]: clean_destination(s.get("name", ""))
                 for s in data.get("stops", [])}

        departures = []
        routes = data.get("timetable", {}).get("routes", [])
        for route in routes:
            # Map intervalId -> final destination (last stop in that interval sequence)
            interval_dest = {}
            for interval in route.get("stationIntervals", []):
                int_stops = interval.get("intervals", [])
                if int_stops:
                    last_id = int_stops[-1].get("stopId", "")
                    interval_dest[interval["id"]] = stops.get(last_id, "")

            for schedule in route.get("schedules", []):
                for journey in schedule.get("knownJourneys", []):
                    hour = int(journey.get("hour", 0))
                    minute = int(journey.get("minute", 0))
                    dest = interval_dest.get(journey.get("intervalId", 0), "")
                    dep_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    departures.append((dep_time, dest))

        _timetable_cache = sorted(departures, key=lambda x: x[0])
        _timetable_fetched_at = now
        return _timetable_cache
    except Exception:
        return _timetable_cache  # keep stale cache on error

def match_timetable_dest(eta_seconds, timetable, tolerance_secs=180):
    """Find the timetable destination whose scheduled time best matches our live ETA."""
    expected = datetime.datetime.now() + datetime.timedelta(seconds=eta_seconds)
    best_dest, best_diff = None, float("inf")
    for dep_time, dest in timetable:
        diff = abs((dep_time - expected).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_dest = dest
    return best_dest if best_diff <= tolerance_secs else None

def get_departures():
    try:
        response = requests.get(ARRIVALS_URL, timeout=10)
        if response.status_code != 200:
            return [("API Error", "")]
        data = response.json()
    except Exception:
        return [("Conn Error", "")]

    met_trains = [t for t in data if t.get("lineName", "").lower() == LINE_ID]
    sorted_trains = sorted(met_trains, key=lambda x: x.get("timeToStation", 0))

    timetable = get_timetable()
    departures = []
    for train in sorted_trains[:3]:
        seconds = train.get("timeToStation", 0)
        minutes = seconds // 60
        time_str = "Due" if minutes == 0 else f"{minutes}m"

        # Try to get the real outbound destination from the timetable
        dest = match_timetable_dest(seconds, timetable)
        if not dest:
            # Fall back to whatever the live API reports
            dest = clean_destination(train.get("destinationName", ""))

        short_dest = dest[:10].strip()
        departures.append((short_dest, time_str))

    return departures

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
            draw.text((2, 0), "METROPOLITAN", fill="white", font=font)
            draw.line((0, 14, 128, 14), fill="white")
            
            # 2. Main Body — pixel-accurate dot padding so time aligns to the right edge
            LEFT_MARGIN = 2
            RIGHT_MARGIN = 2
            USABLE_WIDTH = 128 - LEFT_MARGIN - RIGHT_MARGIN

            y_offset = 18
            if not train_data:
                draw.text((LEFT_MARGIN, y_offset), "No departures", fill="white", font=font)
            else:
                for dest, t_left in train_data:
                    time_w = math.ceil(font.getlength(t_left))
                    time_x = 128 - RIGHT_MARGIN - time_w
                    dest_w = math.ceil(font.getlength(dest))
                    dot_w = math.ceil(font.getlength("."))
                    # Leave a 2px safety gap before the time text
                    available = time_x - LEFT_MARGIN - dest_w - 2
                    num_dots = max(1, available // dot_w)
                    draw.text((LEFT_MARGIN, y_offset), f"{dest}{'.' * num_dots}", fill="white", font=font)
                    draw.text((time_x, y_offset), t_left, fill="white", font=font)
                    y_offset += 15
                    
        time.sleep(60)

if __name__ == "__main__":
    update_display()
