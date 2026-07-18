#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPX Geocoder v3.9
Date: 2025-11-22

Changes in v3.9:
- France: Photon primary (with 1.3s min delay) + BAN fallback
- Province for France = first 2 digits of postcode (from Photon)
- RN / D normalization for French roads
- Map updater runs every 5 seconds (throttled), shows last 200 points only
- Auto-center OFF by default; toggle button to enable
- All previous Italy/Nominatim/monaco logic preserved
- Cache kept (4-decimal rounding)

UI restyled to match GPX Ironer dark cinematic theme.
"""
import os
import sys
import time
import threading
import sqlite3
import json
import re
from datetime import datetime, timezone
import unicodedata
import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import gpxpy
import gpxpy.gpx
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import pycountry
import tkintermapview

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
VERSION   = "v3.9"
AUTHOR    = "Marco Cot"
CONTACT   = "marcocot1982@gmail.com"

SPLASH_SECONDS      = 5
CACHE_DECIMALS      = 4
MAX_POLYLINE_POINTS = 200
TENERIFE_CENTER     = (28.2916, -16.6291)

PHOTON_ENDPOINT  = "https://photon.komoot.io/reverse"
PHOTON_MIN_DELAY = 1.3

ELEVATION_URL   = "https://api.opentopodata.org/v1/srtm30m"
ELEVATION_BATCH = 100
ELEVATION_DELAY = 1.1   # seconds between requests (rate-limit: 1 req/s)

NOMINATIM_USER_AGENT = f"GPXGeocoder/{VERSION} - {CONTACT}"
NOMINATIM_TIMEOUT    = 10
geolocator        = Nominatim(user_agent=NOMINATIM_USER_AGENT, timeout=NOMINATIM_TIMEOUT)
reverse_nominatim = RateLimiter(geolocator.reverse, min_delay_seconds=1, max_retries=3, error_wait_seconds=3)

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CACHE_DB_PATH = os.path.join(SCRIPT_DIR, "geocode_cache.db")

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE  (shared with GPX Ironer)
# ──────────────────────────────────────────────────────────────────────────────
C = {
    "bg":     "#141414",
    "panel":  "#1e1e1e",
    "panel2": "#252525",
    "border": "#333333",
    "accent": "#f5a623",
    "accent2":"#e8941a",
    "green":  "#4caf50",
    "red":    "#e53935",
    "orange": "#fb8c00",
    "blue":   "#2196F3",
    "text":   "#e8e8e8",
    "muted":  "#888888",
    "dim":    "#555555",
}

# ──────────────────────────────────────────────────────────────────────────────
# APP ICON  (GPS pin — amber teardrop + white dot, 16/32/48/64 px, embedded ICO)
# ──────────────────────────────────────────────────────────────────────────────
import base64, tempfile

_ICO_B64 = (
    "AAABAAQAEBAAAAEAIADeAAAARgAAACAgAAABACAARgEAACQBAAAwMAAAAQAgAPEBAABqAgAAQEAA"
    "AAEAIACBAgAAWwQAAIlQTkcNChoKAAAADUlIRFIAAAAQAAAAEAgGAAAAH/P/YQAAAKVJREFUeJy1"
    "UzESwkAI3KO0vvqapLkn+Yl7jI/QJ9l4Teq02l6anEECSgq3YoDdWRgIUJAimpafZgSZ+0h04v0y"
    "aHzkUndC5CXzGndIXrIlQrLgAe8NKaJZ5NP5AQB43Ua1nkvdHFhkGUuYAl78T4DPbe0AWA/p2yIt"
    "5FIxzQjEE0fIHQRsp+kRkef8duAR0X5h912Aftp95p8WuUiKaM/r0Hqs9S30lEfMh8Fx1wAAAABJ"
    "RU5ErkJggolQTkcNChoKAAAADUlIRFIAAAAgAAAAIAgGAAAAc3p69AAAAQ1JREFUeJzVlz0SwiAQ"
    "hTeOlTU1TWw8kpfwMB5Cj5RGm9RptcXCwRFclt0FFF+VH8L79kEIAfixBukD1oCj7s+LrE92Y288"
    "HUey3e5wFYFkG3GNtSDkTWvASY0xEApi1dIc4JkcNW9QgFrmHIgPgNrmOYjkEHxLAUCr6r2wFNba"
    "zjb7S3B+P29V/bwSkFQfm6euYYpT6GsOcERVyk2hCKC2/g+Amu2aN6GfBOYFBv8JzQmrlFt9/HVU"
    "L0TahSdWMASSFDTC9gb9zAGvVimkdkZoArUhqG1ZcghqQaj3hDUgcuZZgBIIjjlAgx8TibkIgAMh"
    "/SsSA1AgGvMiWQPOGnC30+j8saafItp3U23lDz7di4d7/vboAAAAAElFTkSuQmCCiVBORw0KGgoA"
    "AAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAABuElEQVR4nO2aPVLEMAyFBUNFTU0DDUfiEhyGS3Ak"
    "GmioqWmh0oxXK8mS/OwkzL5us4n9PcuR/0J0cF2hC7y/o1/v/69vbJ3DhfWAexo1VH7YAn9/fXCf"
    "e3r5VK9XjZQekvA9aEvSTMVE6gEUuNSIkfCNLTwKXKo1EjVxHblpBbwsO5ocugZWwWt1REy4BlbD"
    "a3X1TIS60Er4bJ2mAXa+BTyL6/aioBoYHV1nyGJyu9CWrR9lODOwx9ZnaWxmBPbQ+iyP5WZWpbfP"
    "Hye/f94ep9QDNyDB5XW0kZMuNJo6LfjsPZqslBoayPYsmIFMy1ajoOkSga11McDKpEdkKv1fEeB1"
    "qLX10VOkZautz0xyrQwfiRnwsFMJ1ixgKfMdqHajGfJYzgygN1+R0tjcLLSHKPQYVAN7jILFZEZg"
    "NKUiZKXOVqGBbAsT0TpdA63zlSYym7zdCKw2kd2hDnWhVSYq2+uHP+BIzUbbgpH7Rm1Z2RSenk7P"
    "SK+RdGkJckqJOOSrDp7lBc3oi42AJ5pw0B2JBgqeCPipQbRLIeGJwN9KeNFAHGprgi7qJRRDz4In"
    "mvC1CpF/SIKeqv8BC5HNZJuJ4QcAAAAASUVORK5CYIKJUE5HDQoaCgAAAA1JSURSAAAAQAAAAEAI"
    "BgAAAKppcd4AAAJISURBVHic7Vs7UsUwDBSU1NQ00HAkLsFhuARHooGGmpoWKs9k/PxZyVrZhmz5"
    "XmJr12tHcWSRE/8bV5Gd3d3KD3Ld51dcXNSOUMI9MAVxb9iLdA3eYrg1hhB/e7mH2np8/uhe4yWE"
    "SyM18ijhHmqCeIgw1ACbeA6GEOYbS+RZxHOUhLCKcG25aSb5Wl/WxVetWt5RJPEScjdonaBywGrk"
    "SzFonQALsCL5hBERIAFWJp9gFUG9CK5IPsESW1cAdmrLBBJ7U4AdrJ9DOxXgKbAD+QRNrFUBdrZ+"
    "jhYXyAE7jX4CGrMpFf5LKKaNR8swRv/m6b34+/frg3tfx1S5lCaHO6BGvvcfC6ECIASjRbgQgLX6"
    "a4ixRChxazrAa/5bCHmJ0OPw758CdAFGRjJiPTgdMDuA2TgFmB3AbNAFGElvGalxjtMBrT+Rj5QI"
    "LCPpNfo9DhcCsL7FawixrD/9bRAhFjHvjwhfA1oEo8mLNL4NsjdFItDbDBE5nwKYAF5Pg0igMVcF"
    "iCxVY6PFBZ4CO7lAE2tTgFy5HUTQFkx0HbDzVEBiVz8FVnaBJTZIgB2mgrVWCHbAyiKMFEqppsCK"
    "IoxWiZkWuNl1giJ+xZKmVLjUUaQbPCtFz1phczQHJCGia4U9chSXt8EUSMQ08CQv4nxihLmHgLzb"
    "W+C6H3AMzNMNLPIipENTnvWFTPIixFNjoyKMJjgowo/NIUJEkRch7wlaEqbo9DrkXR9JmJgnw1oI"
    "2RWukUikZ5EXWfTssEjcTlTodwGUVOQ23C+5fAlgXO45ZAAAAABJRU5ErkJggg=="
)

def _apply_icon(win):
    """Write the embedded ICO to a temp file and apply it via iconbitmap (Windows-safe)."""
    try:
        data = base64.b64decode(_ICO_B64)
        with tempfile.NamedTemporaryFile(suffix=".ico", delete=False) as tf:
            tf.write(data)
            _ico_path = tf.name
        win.iconbitmap(_ico_path)
    except Exception:
        pass   # silently ignore on platforms that don't support ICO

# ──────────────────────────────────────────────────────────────────────────────
# Italian capoluoghi and translations
# ──────────────────────────────────────────────────────────────────────────────
_RAW_CAPOLUOGHI = [
    "Agrigento","Alessandria","Ancona","Aosta","Arezzo","Ascoli Piceno","Asti","Avellino",
    "Bari","Barletta-Andria-Trani","Belluno","Benevento","Bergamo","Biella","Bologna",
    "Bolzano","Brescia","Brindisi","Cagliari","Caltanissetta","Campobasso","Carbonia-Iglesias",
    "Caserta","Catania","Catanzaro","Chieti","Como","Cosenza","Cremona","Crotone","Cuneo",
    "Enna","Fermo","Ferrara","Firenze","Foggia","Forlì-Cesena","Frosinone","Genova","Gorizia",
    "Grosseto","Imperia","Isernia","La Spezia","L'Aquila","Latina","Lecce","Lecco","Livorno",
    "Lodi","Lucca","Macerata","Mantova","Massa-Carrara","Matera","Messina","Milano","Modena",
    "Monza e Brianza","Napoli","Novara","Nuoro","Oristano","Padova","Palermo","Parma","Pavia",
    "Perugia","Pesaro e Urbino","Pescara","Piacenza","Pisa","Pistoia","Pordenone","Potenza",
    "Prato","Ragusa","Ravenna","Reggio Calabria","Reggio Emilia","Rieti","Rimini","Roma",
    "Rovigo","Salerno","Sassari","Savona","Siena","Siracusa","Sondrio","Taranto","Teramo",
    "Terni","Torino","Trapani","Trento","Treviso","Trieste","Udine","Varese","Venezia",
    "Verbano-Cusio-Ossola","Vercelli","Verona","Vibo Valentia","Vicenza","Viterbo"
]
def _normalize_for_set(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.strip().lower()
CAPOLUOGHI_SET = {_normalize_for_set(n) for n in _RAW_CAPOLUOGHI}

EN_TO_IT = {"milan": "Milano", "turin": "Torino", "genoa": "Genova",
            "florence": "Firenze", "rome": "Roma"}

VENTITRE_RE = re.compile(r"ventitreesimo", flags=re.IGNORECASE)
def postprocess_road_ventitre(road: str) -> str:
    if not road: return road
    return VENTITRE_RE.sub("XXIII", road)

# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────
def ensure_cache_db(path=CACHE_DB_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS geocode_cache (
        key TEXT PRIMARY KEY,
        lat REAL, lon REAL,
        road TEXT, town TEXT, province TEXT,
        country3 TEXT, country2 TEXT, source TEXT, timestamp TEXT
    )""")
    conn.commit(); conn.close()

def cache_key(lat: float, lon: float) -> str:
    return f"{round(lat, CACHE_DECIMALS)}_{round(lon, CACHE_DECIMALS)}"

def cache_get(conn: sqlite3.Connection, key: str):
    cur = conn.cursor()
    cur.execute("SELECT lat,lon,road,town,province,country3,country2,source,timestamp FROM geocode_cache WHERE key=?", (key,))
    r = cur.fetchone()
    if not r: return None
    return {"lat":r[0],"lon":r[1],"road":r[2],"town":r[3],"province":r[4],
            "country3":r[5],"country2":r[6],"source":r[7],"timestamp":r[8]}

def cache_set(conn: sqlite3.Connection, key: str, lat: float, lon: float,
              road: str, town: str, province: str, country3: str, country2: str, source: str):
    cur = conn.cursor()
    ts = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT OR REPLACE INTO geocode_cache
        (key,lat,lon,road,town,province,country3,country2,source,timestamp)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (key,lat,lon,road,town,province,country3,country2,source,ts))
    conn.commit()

def cache_count(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM geocode_cache")
    r = cur.fetchone()
    return r[0] if r else 0

# ──────────────────────────────────────────────────────────────────────────────
# Elevation helpers
# ──────────────────────────────────────────────────────────────────────────────
def gpx_has_elevation(gpx_points) -> bool:
    """Return True if at least one point already carries elevation data."""
    return any(pt.elevation is not None for pt in gpx_points)

def fetch_elevation(gpx_points, overwrite=True, status_cb=None, stop_check=None, map_cb=None):
    """
    Fetch SRTM 30m elevation from opentopodata.org and apply to gpx_points in-place.
    overwrite=False leaves points that already have elevation untouched.
    map_cb(done_up_to) is called after each batch with the index of the last processed point.
    Returns (filled_count, error_count).
    """
    total  = len(gpx_points)
    filled = 0
    errors = 0
    for start in range(0, total, ELEVATION_BATCH):
        if stop_check and stop_check():
            break
        batch   = gpx_points[start:start + ELEVATION_BATCH]
        indices = [i for i, pt in enumerate(batch)
                   if overwrite or pt.elevation is None]
        if not indices:
            if map_cb: map_cb(start + ELEVATION_BATCH)
            continue
        locs          = "|".join(f"{batch[i].latitude},{batch[i].longitude}" for i in indices)
        batch_n       = start // ELEVATION_BATCH + 1
        total_batches = (total + ELEVATION_BATCH - 1) // ELEVATION_BATCH
        pct           = int(start / total * 100)
        if status_cb:
            status_cb(batch_n, total_batches, pct, start, total)
        try:
            r = requests.get(ELEVATION_URL, params={"locations": locs}, timeout=15)
            r.raise_for_status()
            for k, result in enumerate(r.json().get("results", [])):
                ele = result.get("elevation")
                if ele is not None:
                    batch[indices[k]].elevation = ele
                    filled += 1
        except Exception:
            errors += 1
        if map_cb:
            map_cb(min(start + ELEVATION_BATCH, total))
        if start + ELEVATION_BATCH < total:
            time.sleep(ELEVATION_DELAY)
    return filled, errors

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def country_alpha2_to_alpha3(alpha2: str) -> str:
    if not alpha2: return ""
    try:    return pycountry.countries.get(alpha_2=alpha2.upper()).alpha_3
    except: return alpha2.upper()

def strip_leading_house_number(s: str) -> str:
    if not s: return s
    s = s.strip()
    s2 = re.sub(r'^\s*\d+\s*[-/A-Za-z]*\s+', '', s)
    return s2.strip()

RN_PAT = re.compile(r'\broute\s*nationale\b\s*\.?\s*([0-9A-Za-z\-]+)', flags=re.IGNORECASE)
D_PAT  = re.compile(r'\broute\s*(?:d[eé]partementale|departementale|dept|dpt)\b\s*\.?\s*([0-9A-Za-z\-]+)', flags=re.IGNORECASE)
def normalize_french_road(road: str) -> str:
    if not road: return road
    s = RN_PAT.sub(r'RN \1', road)
    s = D_PAT.sub(r'D \1', s)
    return s

# ──────────────────────────────────────────────────────────────────────────────
# Photon (France)
# ──────────────────────────────────────────────────────────────────────────────
_photon_lock      = threading.Lock()
_photon_last_call = 0.0

def photon_reverse(lat: float, lon: float, timeout=8):
    global _photon_last_call
    try:
        with _photon_lock:
            now = time.time()
            since = now - _photon_last_call
            if since < PHOTON_MIN_DELAY:
                time.sleep(PHOTON_MIN_DELAY - since)
            params = {"lat": lat, "lon": lon, "lang": "fr", "limit": 1}
            r = requests.get(PHOTON_ENDPOINT, params=params, timeout=timeout)
            _photon_last_call = time.time()
        r.raise_for_status()
        data = r.json()
        features = data.get("features", [])
        if not features: return None
        props    = features[0].get("properties", {}) or {}
        road     = strip_leading_house_number(props.get("street") or props.get("name") or "")
        town     = props.get("city") or props.get("town") or props.get("village") or props.get("locality") or ""
        postcode = props.get("postcode") or ""
        province = postcode[:2] if postcode and len(postcode) >= 2 else ""
        country2 = (props.get("country") or "FR")
        country2_up = (country2 or "").upper()
        if country2_up == "FRANCE": country2_up = "FR"
        country3 = country_alpha2_to_alpha3(country2_up)
        return {"road": road, "town": town, "province": province.upper(),
                "country2": country2_up, "country3": country3, "source": "photon"}
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────────────────────
# BAN — Base Adresse Nationale (France fallback)
# ──────────────────────────────────────────────────────────────────────────────
BAN_ENDPOINT = "https://api-adresse.data.gouv.fr/reverse/"

def ban_reverse(lat: float, lon: float, timeout=8):
    try:
        params = {"lon": lon, "lat": lat, "limit": 1}
        r = requests.get(BAN_ENDPOINT, params=params, timeout=timeout)
        r.raise_for_status()
        features = r.json().get("features", [])
        if not features: return None
        props   = features[0].get("properties", {}) or {}
        road    = strip_leading_house_number(props.get("street") or props.get("name") or "")
        town    = props.get("city") or ""
        context = props.get("context") or ""
        if context:
            province = context.split(",")[0].strip().zfill(2)
        else:
            postcode = props.get("postcode") or ""
            province = postcode[:2] if len(postcode) >= 2 else ""
        return {"road": road, "town": town, "province": province.upper(),
                "country2": "FR", "country3": country_alpha2_to_alpha3("FR"), "source": "ban"}
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────────────────────
# Core extraction
# ──────────────────────────────────────────────────────────────────────────────
def extract_address_components_cached(conn: sqlite3.Connection, lat: float, lon: float):
    key    = cache_key(lat, lon)
    cached = cache_get(conn, key)
    if cached:
        return (cached["road"], cached["town"], cached["province"],
                cached["country3"], cached["country2"], cached["source"])

    loc = None
    try:    loc = reverse_nominatim((lat, lon), language="en", addressdetails=True)
    except: loc = None

    addr = {}
    if loc and getattr(loc, "raw", None):
        addr = loc.raw.get("address", {}) or {}

    country2    = (addr.get("country_code") or "") or ""
    country2_up = country2.upper() if country2 else ""

    if not country2_up:
        try:
            raw = geolocator.reverse((lat, lon), language="en", addressdetails=True)
            if getattr(raw, "raw", None):
                addr = raw.raw.get("address", {}) or {}
                country2    = (addr.get("country_code") or "") or ""
                country2_up = country2.upper() if country2 else ""
        except Exception:
            country2_up = ""

    is_france = country2_up in ("FR", "FRANCE")

    if is_france:
        res = photon_reverse(lat, lon)
        if not res: res = ban_reverse(lat, lon)
        if res:
            road            = res.get("road", "")     or ""
            province        = res.get("province", "") or ""
            country2_final  = res.get("country2", "FR") or "FR"
            country3        = res.get("country3", "") or country_alpha2_to_alpha3("FR")
            source          = res.get("source", "unknown")
            road            = normalize_french_road(road)
            _nom_city       = addr.get("city") or ""
            _confirmed_city = _nom_city if (addr.get("suburb") or addr.get("city_district")) else ""
            town = (addr.get("village") or addr.get("hamlet") or addr.get("town") or _confirmed_city or "")
        else:
            road           = (addr.get("road") or addr.get("residential") or addr.get("pedestrian") or "") or ""
            _nom_city      = addr.get("city") or ""
            _confirmed_city= _nom_city if (addr.get("suburb") or addr.get("city_district")) else ""
            town           = (addr.get("village") or addr.get("hamlet") or addr.get("town") or _confirmed_city or "")
            postcode       = (addr.get("postcode") or "") or ""
            province       = postcode[:2] if postcode and len(postcode) >= 2 else ""
            country2_final = "FR"
            country3       = country_alpha2_to_alpha3(country2_final)
            source         = "nominatim"
            road           = normalize_french_road(road)
    else:
        road = (addr.get("road") or addr.get("residential") or addr.get("pedestrian") or addr.get("footway") or "") or ""
        if country2_up == "IT":
            town  = (addr.get("municipality") or addr.get("city") or addr.get("town")
                     or addr.get("village") or addr.get("locality") or "") or ""
            tnorm = town.strip().lower()
            if tnorm in EN_TO_IT: town = EN_TO_IT[tnorm]
        else:
            town = (addr.get("city") or addr.get("town") or addr.get("municipality")
                    or addr.get("village") or addr.get("locality") or "") or ""
        province = ""
        for k in addr.keys():
            if k.upper().startswith("ISO3166"):
                v = addr.get(k) or ""
                if "-" in v:
                    province = v.split("-")[-1].upper()
                    break
        if not province:
            prov_raw = (addr.get("county") or addr.get("state_district") or addr.get("region") or "") or ""
            if prov_raw.lower().startswith("provincia di "):
                prov_raw = prov_raw[len("provincia di "):].strip()
            province = prov_raw.upper() if prov_raw else ""
        country2_final = country2_up or ""
        country3       = country_alpha2_to_alpha3(country2_final) if country2_final else ""
        source         = "nominatim"

    if (country2_final or "").upper() == "MC":
        province = ""
    road = postprocess_road_ventitre(road)
    if (country2_final or "").upper() == "IT" and town:
        if _normalize_for_set(town) in CAPOLUOGHI_SET:
            province = ""

    # ── Town alias corrections ────────────────────────────────────────────────
    _TOWN_ALIASES = {
        "vallecrosia al mare": "Vallecrosia",
    }
    if town and town.strip().lower() in _TOWN_ALIASES:
        town = _TOWN_ALIASES[town.strip().lower()]

    road           = road or ""
    town           = town or ""
    province       = province or ""
    country3       = country3 or ""
    country2_final = country2_final or ""
    source         = source or "unknown"

    try:
        cache_set(conn, key, lat, lon, road, town, province, country3, country2_final, source)
    except Exception:
        pass
    return road, town, province, country3, country2_final, source

# ──────────────────────────────────────────────────────────────────────────────
# Format comment
# ──────────────────────────────────────────────────────────────────────────────
def format_cmt(road: str, town: str, province: str, country3: str, choice: int) -> str:
    if choice == 1:
        return ", ".join(filter(None, [road, town]))
    elif choice == 2:
        base = ", ".join(filter(None, [road, town]))
        return f"{base} ({province})" if province else base
    else:
        return " | ".join(filter(None, [road, town, province, country3]))

# ──────────────────────────────────────────────────────────────────────────────
# UI helpers  (matching GPX Ironer)
# ──────────────────────────────────────────────────────────────────────────────
def mk_btn(parent, text, bg, cmd, width=None, font=("segoe UI",9,"bold")):
    kw = dict(text=text, bg=bg,
              fg="white" if bg not in (C["dim"], C["panel2"]) else C["muted"],
              activebackground=bg, activeforeground="white",
              relief="flat", cursor="hand2", command=cmd,
              font=font, pady=4, padx=8)
    if width: kw["width"] = width
    return tk.Button(parent, **kw)

def sec_hdr(parent, text):
    f = tk.Frame(parent, bg=C["panel"]); f.pack(fill="x", padx=10, pady=(12,3))
    tk.Label(f, text=text, font=("segoe UI",8,"bold"),
             bg=C["panel"], fg=C["accent"]).pack(side="left")
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=10)

# ──────────────────────────────────────────────────────────────────────────────
# GUI — root window
# ──────────────────────────────────────────────────────────────────────────────
ensure_cache_db(CACHE_DB_PATH)
db_conn = sqlite3.connect(CACHE_DB_PATH, check_same_thread=False)

root = tk.Tk()
_apply_icon(root)
root.title(f"GPX Geocoder  {VERSION}")
root.configure(bg=C["bg"])
try:    root.state("zoomed")
except: root.geometry("1440x860")
root.resizable(True, True)

# ── ttk style ────────────────────────────────────────────────────────────────
sty = ttk.Style(root); sty.theme_use("clam")
sty.configure(".",                  background=C["bg"],    foreground=C["text"])
sty.configure("TLabel",             background=C["bg"],    foreground=C["text"], font=("segoe UI",9))
sty.configure("TFrame",             background=C["bg"])
sty.configure("TEntry",             fieldbackground=C["panel2"], foreground=C["text"],
                                    insertcolor=C["text"], font=("segoe UI",9))
sty.configure("TScrollbar",         background=C["panel2"], troughcolor=C["border"],
                                    arrowcolor=C["muted"])
sty.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor=C["panel2"],
                                    bordercolor=C["border"], lightcolor=C["accent"],
                                    darkcolor=C["accent2"])

# ──────────────────────────────────────────────────────────────────────────────
# Splash
# ──────────────────────────────────────────────────────────────────────────────
def show_splash_then_main():
    sp = tk.Toplevel(root); sp.overrideredirect(True); sp.configure(bg=C["bg"])
    sw, sh = sp.winfo_screenwidth(), sp.winfo_screenheight()
    w, h   = 620, 300; sp.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x")
    body = tk.Frame(sp, bg=C["bg"]); body.pack(expand=True, fill="both", padx=40)
    tk.Label(body, text="GPX REVERSE GEOCODER",
             font=("segoe UI",22,"bold"), bg=C["bg"], fg=C["accent"]).pack(pady=(28,4))
    tk.Label(body, text=f"{VERSION}  ·  by {AUTHOR}  ·  {datetime.now().year}",
             font=("segoe UI",9), bg=C["bg"], fg=C["muted"]).pack()
    tk.Label(body, text="Name your roads - Gotta cache 'em all!",
             font=("segoe UI",9,"italic"), bg=C["bg"], fg=C["dim"]).pack(pady=(4,16))
    pbv = tk.DoubleVar()
    pb  = ttk.Progressbar(body, variable=pbv, maximum=100, length=540); pb.pack()
    pct = tk.Label(body, text="0%", font=("segoe UI",8), bg=C["bg"], fg=C["dim"])
    pct.pack(pady=4)
    tk.Frame(sp, bg=C["accent"], height=3).pack(fill="x", side="bottom")

    steps      = max(15, SPLASH_SECONDS * 20)
    interval_ms = int(SPLASH_SECONDS * 1000 / steps)

    def _step(i):
        if not sp.winfo_exists():
            return
        pct_val = int(i / steps * 100)
        pbv.set(pct_val)
        pct.config(text=f"{pct_val}%")
        if i < steps:
            root.after(interval_ms, _step, i + 1)
        else:
            sp.destroy()
            root.deiconify()
            try: root.state("zoomed")
            except: pass

    root.withdraw()
    root.after(interval_ms, _step, 1)

show_splash_then_main()

# ──────────────────────────────────────────────────────────────────────────────
# Top chrome
# ──────────────────────────────────────────────────────────────────────────────
tk.Frame(root, bg=C["accent"], height=3).pack(fill="x")
tb = tk.Frame(root, bg=C["bg"]); tb.pack(fill="x", padx=16, pady=5)
tk.Label(tb, text="GPX GEOCODER",
         font=("segoe UI",13,"bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")
tk.Label(tb, text=f"{VERSION}  ·  {AUTHOR}  ·  2025–{datetime.now().year}",
         font=("segoe UI",8), bg=C["bg"], fg=C["dim"]).pack(side="right")
tk.Frame(root, bg=C["border"], height=1).pack(fill="x")

# ──────────────────────────────────────────────────────────────────────────────
# Menu
# ──────────────────────────────────────────────────────────────────────────────
menubar  = tk.Menu(root,    bg=C["panel"], fg=C["text"],
                   activebackground=C["accent"], activeforeground="black", relief="flat")
filemenu = tk.Menu(menubar, tearoff=0, bg=C["panel"], fg=C["text"],
                   activebackground=C["accent"], activeforeground="black")
filemenu.add_command(label="Import GPX…", command=lambda: start_processing_from_button())
idx_pause = 1
pause_event      = threading.Event(); pause_event.set()
stop_event       = threading.Event()
processing_state = {"running": False, "thread": None}
pause_btn_ref    = [None]

def toggle_pause_resume():
    if not processing_state["running"]:
        messagebox.showinfo("Pause/Resume", "No active processing.")
        return
    if pause_event.is_set():
        pause_event.clear()
        filemenu.entryconfigure(idx_pause, label="Resume Processing")
        status_label.config(text="Paused.")
        if pause_btn_ref[0]: pause_btn_ref[0].config(text="▶  Resume")
    else:
        pause_event.set()
        filemenu.entryconfigure(idx_pause, label="Pause Processing")
        status_label.config(text="Resumed.")
        if pause_btn_ref[0]: pause_btn_ref[0].config(text="⏸  Pause")

filemenu.add_command(label="Pause Processing", command=toggle_pause_resume)

def open_cache_editor():
    candidates = ["Cache_Editor.pyw","Cache_Editor.py","cache_editor.pyw","cache_editor.py"]
    for c in candidates:
        p = os.path.join(SCRIPT_DIR, c)
        if os.path.exists(p):
            try:
                if sys.platform.startswith("win"): os.startfile(p)
                else: threading.Thread(target=lambda: os.system(f'"{sys.executable}" "{p}"'), daemon=True).start()
                return
            except Exception: pass
    path = filedialog.askopenfilename(title="Select Cache Editor", filetypes=[("Python files","*.py *.pyw")])
    if path:
        try:
            if sys.platform.startswith("win"): os.startfile(path)
            else: threading.Thread(target=lambda: os.system(f'"{sys.executable}" "{path}"'), daemon=True).start()
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open Cache Editor: {e}")

filemenu.add_command(label="Open Cache Editor", command=open_cache_editor)
filemenu.add_separator()
filemenu.add_command(label="Exit", command=root.destroy)
menubar.add_cascade(label="File", menu=filemenu)

helpmenu = tk.Menu(menubar, tearoff=0, bg=C["panel"], fg=C["text"],
                   activebackground=C["accent"], activeforeground="black")
def about_dialog():
    messagebox.showinfo("About", f"GPX Geocoder\nVersion {VERSION}\nAuthor: {AUTHOR}\nContact: {CONTACT}")
helpmenu.add_command(label="About", command=about_dialog)
menubar.add_cascade(label="Help", menu=helpmenu)
root.config(menu=menubar)

# ──────────────────────────────────────────────────────────────────────────────
# Body layout
# ──────────────────────────────────────────────────────────────────────────────
body_frame = tk.Frame(root, bg=C["bg"])
body_frame.pack(fill="both", expand=True)

# ── LEFT SIDEBAR ──────────────────────────────────────────────────────────────
left = tk.Frame(body_frame, bg=C["panel"], width=240)
left.pack(side="left", fill="y", padx=(10,0), pady=10)
left.pack_propagate(False)

# Radio button shared style
_radio_kw = dict(bg=C["panel"], fg=C["text"],
                 activebackground=C["panel"], activeforeground=C["accent"],
                 selectcolor=C["accent2"], font=("segoe UI",8),
                 anchor="w", relief="flat")

# FILE
sec_hdr(left, "FILE")
fr = tk.Frame(left, bg=C["panel"]); fr.pack(fill="x", padx=10, pady=6)
start_button = mk_btn(fr, "📂  Select & Process GPX", C["green"], lambda: None)
start_button.pack(fill="x", pady=2)

# COMMENT FORMAT
sec_hdr(left, "COMMENT FORMAT")
fmt = tk.Frame(left, bg=C["panel"]); fmt.pack(fill="x", padx=10, pady=6)
cmt_choice = tk.IntVar(value=2)
tk.Radiobutton(fmt, text="Road, Town",
               variable=cmt_choice, value=1, **_radio_kw).pack(fill="x", pady=1)
tk.Radiobutton(fmt, text="Road, Town (Province)",
               variable=cmt_choice, value=2, **_radio_kw).pack(fill="x", pady=1)
tk.Radiobutton(fmt, text="Road | Town | Province | Country",
               variable=cmt_choice, value=3, **_radio_kw).pack(fill="x", pady=1)

# SAVE TO
sec_hdr(left, "SAVE TO")
dst = tk.Frame(left, bg=C["panel"]); dst.pack(fill="x", padx=10, pady=6)
destination_choice = tk.IntVar(value=2)
tk.Radiobutton(dst, text="Original Folder",
               variable=destination_choice, value=1, **_radio_kw).pack(fill="x", pady=1)
tk.Radiobutton(dst, text="Desktop/Geocoded",
               variable=destination_choice, value=2, **_radio_kw).pack(fill="x", pady=1)
tk.Radiobutton(dst, text="Select Folder…",
               variable=destination_choice, value=3, **_radio_kw).pack(fill="x", pady=1)

# PROCESSING
sec_hdr(left, "PROCESSING")
pr = tk.Frame(left, bg=C["panel"]); pr.pack(fill="x", padx=10, pady=6)
_pause_btn = mk_btn(pr, "⏸  Pause", C["orange"], toggle_pause_resume)
_pause_btn.pack(fill="x", pady=2)
pause_btn_ref[0] = _pause_btn
mk_btn(pr, "⏹  Stop & Save",     C["red"],  lambda: stop_and_save()).pack(fill="x", pady=2)
mk_btn(pr, "⏭  Start from Point…", C["blue"], lambda: open_start_from_point_dialog()).pack(fill="x", pady=2)
tk.Label(pr, text="Pause · Stop & save partial\nStart from a specific timestamp",
         font=("segoe UI",7), bg=C["panel"], fg=C["dim"],
         justify="left").pack(anchor="w", padx=2, pady=(4,0))

# AUTO-SAVE
sec_hdr(left, "AUTO-SAVE")
asf = tk.Frame(left, bg=C["panel"]); asf.pack(fill="x", padx=10, pady=6)
asr = tk.Frame(asf, bg=C["panel"]); asr.pack(fill="x")
tk.Label(asr, text="Every", font=("segoe UI",8), bg=C["panel"], fg=C["muted"]).pack(side="left")
autosave_var    = tk.IntVar(value=1000)
_autosave_entry = tk.Spinbox(asr, from_=10, to=100000, increment=100,
                              textvariable=autosave_var, width=7,
                              bg=C["panel2"], fg=C["text"], insertbackground=C["text"],
                              buttonbackground=C["panel"], font=("segoe UI",9),
                              relief="flat", highlightthickness=0)
_autosave_entry.pack(side="left", padx=6)
tk.Label(asr, text="pts", font=("segoe UI",8), bg=C["panel"], fg=C["muted"]).pack(side="left")

# CACHE
sec_hdr(left, "CACHE")
cf = tk.Frame(left, bg=C["panel"]); cf.pack(fill="x", padx=10, pady=6)
cache_count_label = tk.Label(cf, text="—", font=("segoe UI",8), bg=C["panel"], fg=C["muted"])
cache_count_label.pack(anchor="w")

def refresh_cache_count_label():
    try:
        cnt = cache_count(db_conn)
        cache_count_label.config(text=f"Entries: {cnt:,}")
    except Exception:
        cache_count_label.config(text="Entries: ?")

# NOTEPAD
sec_hdr(left, "NOTEPAD")
nf = tk.Frame(left, bg=C["accent"], padx=1, pady=1)
nf.pack(fill="both", expand=True, padx=10, pady=(4,10))
ni = tk.Frame(nf, bg=C["panel2"]); ni.pack(fill="both", expand=True)
notepad = tk.Text(ni, bg=C["panel2"], fg=C["text"],
                   insertbackground=C["text"], font=("segoe UI",8),
                   relief="flat", borderwidth=0, wrap="word",
                   undo=True)
notepad.pack(fill="both", expand=True, padx=4, pady=4)

# ── RIGHT AREA ────────────────────────────────────────────────────────────────
right = tk.Frame(body_frame, bg=C["bg"])
right.pack(side="left", fill="both", expand=True, padx=10, pady=10)

# top bar: section label + zoom + autocenter
rh = tk.Frame(right, bg=C["bg"]); rh.pack(fill="x", pady=(0,6))
tk.Label(rh, text="PREVIEW  &  MAP",
         font=("segoe UI",8,"bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

zf = tk.Frame(rh, bg=C["bg"]); zf.pack(side="right")
autocenter_var = tk.BooleanVar(value=False)
current_zoom   = [10]

def toggle_autocenter():
    v = autocenter_var.get()
    if v:   autocenter_btn.config(text="⊙  Auto-center: ON",  bg=C["accent"],  fg="black")
    else:   autocenter_btn.config(text="⊙  Auto-center: OFF", bg=C["dim"],     fg=C["muted"])

autocenter_btn = mk_btn(zf, "⊙  Auto-center: OFF", C["dim"],
                        lambda: (autocenter_var.set(not autocenter_var.get()), toggle_autocenter()),
                        font=("segoe UI",8))
autocenter_btn.pack(side="right", padx=(6,0))

def zoom_in():
    z = min(map_widget.zoom+1, 19); map_widget.set_zoom(z); current_zoom[0] = z
def zoom_out():
    z = max(map_widget.zoom-1, 3); map_widget.set_zoom(z); current_zoom[0] = z

mk_btn(zf, "＋", C["panel2"], zoom_in,  font=("segoe UI",11,"bold")).pack(side="right", padx=2)
mk_btn(zf, "－", C["panel2"], zoom_out, font=("segoe UI",11,"bold")).pack(side="right", padx=2)

# content row: preview text (left) + map (right)
content = tk.Frame(right, bg=C["bg"]); content.pack(fill="both", expand=True)

# — Preview text ——————————————————————————————————————————————————————————————
text_outer = tk.Frame(content, bg=C["bg"], width=572)
text_outer.pack(side="left", fill="both", padx=(0,8))
text_outer.pack_propagate(False)

th = tk.Frame(text_outer, bg=C["bg"]); th.pack(fill="x", pady=(0,4))
tk.Label(th, text="OUTPUT PREVIEW",
         font=("segoe UI",8,"bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

text_border = tk.Frame(text_outer, bg=C["accent"], padx=1, pady=1)
text_border.pack(fill="both", expand=True)
text_inner = tk.Frame(text_border, bg=C["panel2"])
text_inner.pack(fill="both", expand=True)

tsb = ttk.Scrollbar(text_inner, orient="vertical")
tsb.pack(side="right", fill="y")
preview_text = tk.Text(text_inner, width=52, bg=C["panel2"], fg=C["text"],
                        insertbackground=C["text"], font=("segoe UI",9),
                        relief="flat", borderwidth=0, wrap="word",
                        yscrollcommand=tsb.set)
preview_text.pack(side="left", fill="both", expand=True)
tsb.config(command=preview_text.yview)

# — Map ———————————————————————————————————————————————————————————————————————
map_outer = tk.Frame(content, bg=C["bg"])
map_outer.pack(side="left", fill="both", expand=True)

mh2 = tk.Frame(map_outer, bg=C["bg"]); mh2.pack(fill="x", pady=(0,4))
tk.Label(mh2, text="TRACK MAP",
         font=("segoe UI",8,"bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

map_border = tk.Frame(map_outer, bg=C["accent"], padx=2, pady=2)
map_border.pack(fill="both", expand=True)
map_widget = tkintermapview.TkinterMapView(map_border, corner_radius=0)
map_widget.pack(fill="both", expand=True)
map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
map_widget.set_position(*TENERIFE_CENTER)
map_widget.set_zoom(10)

# ── STATUS BAR ────────────────────────────────────────────────────────────────
sb = tk.Frame(root, bg=C["panel"], height=26)
sb.pack(fill="x", side="bottom")
tk.Frame(sb, bg=C["accent"], height=2).pack(fill="x", side="bottom")
status_label = tk.Label(sb, text="Ready. Select GPX file(s) to begin.",
                         font=("segoe UI",8), bg=C["panel"], fg=C["muted"])
status_label.pack(side="left", padx=10, pady=3)
progress_var = tk.DoubleVar()
progress_bar = ttk.Progressbar(sb, variable=progress_var, maximum=100, length=280)
progress_bar.pack(side="left", padx=8, pady=3)
eta_label = tk.Label(sb, text="", font=("segoe UI",8), bg=C["panel"], fg=C["muted"])
eta_label.pack(side="left", padx=6)
# point counter  e.g. "1777 / 2125 pts"
point_counter_label = tk.Label(sb, text="—  /  —  pts",
                                font=("segoe UI",8,"bold"), bg=C["panel"], fg=C["accent"])
point_counter_label.pack(side="left", padx=(4,0))
tk.Label(sb, text="·", font=("segoe UI",8), bg=C["panel"], fg=C["dim"]).pack(side="left", padx=4)
# file counter  e.g. "file 1 / 3"
file_counter_label = tk.Label(sb, text="file  —  /  —",
                               font=("segoe UI",8), bg=C["panel"], fg=C["muted"])
file_counter_label.pack(side="left")

# ──────────────────────────────────────────────────────────────────────────────
# Map drawing helpers (periodic updater)
# ──────────────────────────────────────────────────────────────────────────────
path_obj           = [None]
last_marker        = [None]
map_coords_buffer  = []
map_buffer_lock    = threading.Lock()
map_update_interval = 5.0

def draw_map_now():
    with map_buffer_lock:
        coords = list(map_coords_buffer[-MAX_POLYLINE_POINTS:])
    if not coords: return
    if path_obj[0]:
        try:    path_obj[0].delete()
        except: pass
        path_obj[0] = None
    if last_marker[0]:
        try:    last_marker[0].delete()
        except: pass
        last_marker[0] = None
    if len(coords) > 1:
        try:    path_obj[0] = map_widget.set_path(coords, color=C["red"], width=2)
        except: path_obj[0] = None
    lat, lon = coords[-1]
    try:
        last_marker[0] = map_widget.set_marker(lat, lon,
                             marker_color_circle=C["red"],
                             marker_color_outside="#b71c1c")
    except Exception: pass
    try:
        if autocenter_var.get():
            map_widget.set_position(lat, lon)
            map_widget.set_zoom(current_zoom[0])
    except Exception: pass

_last_map_update = [0.0]
def schedule_map_update():
    now = time.time()
    if now - _last_map_update[0] >= map_update_interval:
        _last_map_update[0] = now
        try: root.after(0, draw_map_now)
        except Exception: pass

# ──────────────────────────────────────────────────────────────────────────────
# Processing
# ──────────────────────────────────────────────────────────────────────────────
def process_single_file(conn, file_path, cmt_choice_value, dest_choice_value,
                        manual_dest=None, file_idx=1, total_files=1, start_index=0):
    basename = os.path.basename(file_path)
    status_label.config(text=f"Processing ({file_idx}/{total_files}): {basename}")
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            gpx = gpxpy.parse(fh)
    except Exception as e:
        preview_text.insert(tk.END, f"❌ Parse error: {basename}: {e}\n")
        preview_text.see(tk.END)
        return

    all_pts = [pt for trk in gpx.tracks for seg in trk.segments for pt in seg.points]
    total   = len(all_pts)
    if total == 0:
        preview_text.insert(tk.END, f"⚠ No points: {basename}\n")
        preview_text.see(tk.END)
        return

    # strip <extensions> from every point, track and segment
    for pt in all_pts:
        pt.extensions = []
    for trk in gpx.tracks:
        trk.extensions = []
        for seg in trk.segments:
            seg.extensions = []
    gpx.extensions = []

    # ── Phase 1: Elevation ────────────────────────────────────────────────────
    overwrite_ele = True
    if gpx_has_elevation(all_pts):
        _answer = [None]
        _evt    = threading.Event()
        _dialog = [None]  # to hold Toplevel reference
        
        def _ask_ele():
            dlg = tk.Toplevel(root)
            dlg.title("Elevation data found")
            dlg.geometry("400x220")
            dlg.resizable(False, False)
            dlg.transient(root)
            dlg.grab_set()
            _dialog[0] = dlg
            
            frm = tk.Frame(dlg, bg=C["bg"])
            frm.pack(fill="both", expand=True)
            
            lbl = tk.Label(frm, 
                text=f"{basename}\nalready contains elevation data.\n\n"
                     f"Yes  →  overwrite with fresh SRTM data\n"
                     f"No   →  keep existing elevation\n"
                     f"Cancel  →  skip elevation entirely",
                bg=C["bg"], fg=C["text"], font=("segoe UI", 10), justify="left")
            lbl.pack(pady=15, padx=10)
            
            btn_frm = tk.Frame(frm, bg=C["bg"])
            btn_frm.pack(pady=10)
            
            def _on_yes():
                _answer[0] = True
                dlg.destroy()
                _evt.set()
            def _on_no():
                _answer[0] = False
                dlg.destroy()
                _evt.set()
            def _on_cancel():
                _answer[0] = None
                dlg.destroy()
                _evt.set()
            
            btn_yes = tk.Button(btn_frm, text="Yes", width=8, command=_on_yes,
                               bg=C["accent"], fg=C["bg"], font=("segoe UI", 10, "bold"))
            btn_yes.pack(side="left", padx=5)
            btn_no = tk.Button(btn_frm, text="No", width=8, command=_on_no,
                              bg=C["accent"], fg=C["bg"], font=("segoe UI", 10, "bold"))
            btn_no.pack(side="left", padx=5)
            btn_cancel = tk.Button(btn_frm, text="Cancel", width=8, command=_on_cancel,
                                  bg=C["accent"], fg=C["bg"], font=("segoe UI", 10, "bold"))
            btn_cancel.pack(side="left", padx=5)
        
        def _timeout_close():
            if _dialog[0] and _dialog[0].winfo_exists():
                _answer[0] = False   # default to No
                _dialog[0].destroy()
                _evt.set()
        
        root.after(0, _ask_ele)
        root.after(60000, _timeout_close)  # 60 seconds timeout
        _evt.wait()
        
        if _answer[0] is None:        # Cancel → skip elevation phase
            overwrite_ele = None
        elif _answer[0] is False:     # No → keep existing
            overwrite_ele = False

    if overwrite_ele is not None:     # None means skip entirely
        preview_text.insert(tk.END, f"⛰  Fetching elevation for {total:,} points…\n")
        preview_text.see(tk.END)

        # ── Elevation map: draw full track in dim grey, then erase batches as done ──
        _all_coords  = [(pt.latitude, pt.longitude) for pt in all_pts]
        _ele_pending = [None]   # path object for the remaining (undone) portion
        _ele_done    = [None]   # path object for the completed (done) portion

        def _draw_elevation_map_initial():
            map_widget.delete_all_path()
            map_widget.delete_all_marker()
            if len(_all_coords) > 1:
                _ele_pending[0] = map_widget.set_path(_all_coords, color=C["dim"], width=2)
            # fit view to track
            lats = [c[0] for c in _all_coords]; lons = [c[1] for c in _all_coords]
            center = ((min(lats)+max(lats))/2, (min(lons)+max(lons))/2)
            map_widget.set_position(*center)
            span = max(max(lats)-min(lats), max(lons)-min(lons))
            z = 7 if span>5 else 9 if span>2 else 10 if span>1 else 12 if span>0.3 else 13 if span>0.1 else 14
            current_zoom[0] = z; map_widget.set_zoom(z)

        root.after(0, _draw_elevation_map_initial)

        def _ele_map_cb(done_up_to):
            """Called on the worker thread after each batch; schedules UI update via after()."""
            def _update():
                # erase old paths
                for obj in (_ele_pending[0], _ele_done[0]):
                    if obj:
                        try: obj.delete()
                        except: pass
                _ele_pending[0] = None; _ele_done[0] = None
                done_coords    = _all_coords[:done_up_to]
                pending_coords = _all_coords[done_up_to:]
                if len(pending_coords) > 1:
                    _ele_pending[0] = map_widget.set_path(pending_coords, color=C["dim"], width=2)
                if len(done_coords) > 1:
                    _ele_done[0] = map_widget.set_path(done_coords, color=C["green"], width=2)
            root.after(0, _update)

        def _ele_status(batch_n, total_batches, pct, done, tot):
            status_label.config(
                text=f"⛰  Elevation batch {batch_n}/{total_batches}  ·  {pct}%  ·  {done:,}/{tot:,} pts")
            point_counter_label.config(text=f"{done:,}  /  {tot:,}  pts")
            progress_var.set(pct * 0.5)   # elevation uses first 50% of the bar

        filled, errors = fetch_elevation(
            all_pts,
            overwrite=overwrite_ele,
            status_cb=_ele_status,
            stop_check=lambda: stop_event.is_set(),
            map_cb=_ele_map_cb)

        preview_text.insert(tk.END,
            f"⛰  Elevation done — {filled:,}/{total:,} pts"
            f"{'' if errors == 0 else f'  ({errors} error(s))'}\n\n")
        preview_text.see(tk.END)
        progress_var.set(50)

        # clear elevation paths before geocoding view takes over
        def _clear_ele_map():
            for obj in (_ele_pending[0], _ele_done[0]):
                if obj:
                    try: obj.delete()
                    except: pass
            _ele_pending[0] = None; _ele_done[0] = None
            map_widget.delete_all_path()
            map_widget.delete_all_marker()
        root.after(0, _clear_ele_map)
        with map_buffer_lock: map_coords_buffer.clear()

    # ── Phase 2: Reverse geocoding ────────────────────────────────────────────
    # determine output path
    stem = os.path.splitext(basename)[0]
    if dest_choice_value == 1:
        out_dir = os.path.dirname(file_path)
    elif dest_choice_value == 2:
        out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Geocoded")
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_dir = manual_dest or os.path.dirname(file_path)
    out_path      = os.path.join(out_dir, stem + "_geocoded.gpx")
    last_temp_path = [None]

    autosave_n = autosave_var.get()
    geocoded   = 0
    t_start    = time.time()
    stopped_early = False

    with map_buffer_lock: map_coords_buffer.clear()

    for i, pt in enumerate(all_pts):
        if i < start_index:
            continue

        # pause support
        while not pause_event.is_set():
            if stop_event.is_set(): break
            time.sleep(0.2)
        if stop_event.is_set():
            stopped_early = True
            break

        lat, lon = pt.latitude, pt.longitude
        try:
            road, town, province, country3, country2, source = \
                extract_address_components_cached(conn, lat, lon)
            cmt = format_cmt(road, town, province, country3, cmt_choice_value)
            pt.comment = cmt
        except Exception as e:
            pt.comment = ""
            cmt = f"[error: {e}]"

        geocoded += 1
        with map_buffer_lock:
            map_coords_buffer.append((lat, lon))
        schedule_map_update()

        # ETA
        elapsed  = time.time() - t_start
        per_pt   = elapsed / geocoded if geocoded else 0
        remain   = (total - i - 1) * per_pt
        eta_str  = f"ETA {int(remain//60)}:{int(remain%60):02d}" if remain > 0 else ""

        # progress — geocoding occupies 50–100% of the bar (0–50% was elevation)
        pct = 50 + ((i + 1) / total) * 50
        try:
            progress_var.set(pct)
            eta_label.config(text=eta_str)
            point_counter_label.config(text=f"{i+1:,} / {total:,} pts".replace(',', '.'))
            file_counter_label.config(text=f"file  {file_idx}  /  {total_files}")
        except Exception: pass

        # preview
        try:
            pt_time = pt.time.strftime("%Y-%m-%d %H:%M:%S") if pt.time else f"#{i+1:05d}"
            preview_text.insert(tk.END, f"{pt_time}  {cmt}\n")
            preview_text.see(tk.END)
        except Exception: pass

        # auto-save
        if geocoded % autosave_n == 0:
            temp_path = os.path.join(out_dir, stem + "_temp.gpx")
            try:
                _gpx_out = gpxpy.gpx.GPX()
                _trk     = gpxpy.gpx.GPXTrack(); _gpx_out.tracks.append(_trk)
                _seg     = gpxpy.gpx.GPXTrackSegment(); _trk.segments.append(_seg)
                for p2 in all_pts[:i+1]: _seg.points.append(p2)
                with open(temp_path, "w", encoding="utf-8") as fh:
                    fh.write(_gpx_out.to_xml())
                last_temp_path[0] = temp_path
                ts = datetime.now().strftime("%H:%M:%S")
                status_label.config(text=f"Auto-saved {geocoded} pts → {os.path.basename(temp_path)}  [{ts}]")
            except Exception as e:
                preview_text.insert(tk.END, f"⚠ Auto-save error: {e}\n")
                preview_text.see(tk.END)

    # final map draw
    try: root.after(0, draw_map_now)
    except Exception: pass

    # save final file
    try:
        pts_to_save = all_pts[:] if not stopped_early else all_pts[:geocoded + start_index]
        _gpx_out = gpxpy.gpx.GPX()
        _trk     = gpxpy.gpx.GPXTrack(); _gpx_out.tracks.append(_trk)
        _seg     = gpxpy.gpx.GPXTrackSegment(); _trk.segments.append(_seg)
        for p2 in pts_to_save: _seg.points.append(p2)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(_gpx_out.to_xml())
        if last_temp_path[0] and os.path.exists(last_temp_path[0]):
            try:    os.remove(last_temp_path[0])
            except: pass
        preview_text.insert(tk.END, f"\n✅ Saved: {out_path}\n")
        preview_text.see(tk.END)
    except Exception as e:
        preview_text.insert(tk.END, f"\n❌ Save failed: {e}\n")
        preview_text.see(tk.END)

    refresh_cache_count_label()
    if stopped_early:
        status_label.config(text=f"Stopped (partial saved): {basename}")
        return None
    else:
        status_label.config(text=f"Completed: {basename}")
    progress_var.set(0)
    eta_label.config(text="")
    point_counter_label.config(text="—  /  —  pts")
    file_counter_label.config(text="file  —  /  —")
    return out_path

# ──────────────────────────────────────────────────────────────────────────────
# Completion dialog
# ──────────────────────────────────────────────────────────────────────────────
def show_completion_dialog(completed_paths):
    """Styled dialog listing all geocoded output files.
    User can open one in Cache Editor or send one or more to Towns Video."""
    d = tk.Toplevel(root)
    d.title("Processing Complete")
    d.configure(bg=C["bg"])
    d.geometry("580x440")
    d.resizable(False, True)
    d.grab_set()
    d.lift()

    tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")
    tk.Label(d, text="PROCESSING COMPLETE",
             font=("segoe UI",10,"bold"), bg=C["bg"], fg=C["accent"]).pack(padx=16, pady=(12,2), anchor="w")
    tk.Label(d, text=f"{len(completed_paths)} file(s) geocoded successfully.",
             font=("segoe UI",8), bg=C["bg"], fg=C["muted"]).pack(padx=16, anchor="w")
    tk.Label(d, text="Select file(s) and choose what to do next:",
             font=("segoe UI",8), bg=C["bg"], fg=C["dim"]).pack(padx=16, pady=(2,8), anchor="w")
    tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16)

    # listbox — multi-select so user can send several files to Towns Video at once
    lf = tk.Frame(d, bg=C["accent"], padx=1, pady=1)
    lf.pack(fill="both", expand=True, padx=16, pady=8)
    li = tk.Frame(lf, bg=C["panel2"]); li.pack(fill="both", expand=True)
    lsb = ttk.Scrollbar(li, orient="vertical"); lsb.pack(side="right", fill="y")
    listbox = tk.Listbox(li, yscrollcommand=lsb.set, font=("segoe UI",8),
                          bg=C["panel2"], fg=C["text"],
                          selectbackground=C["accent"], selectforeground="black",
                          activestyle="none", relief="flat", borderwidth=0,
                          selectmode="extended")   # extended = Shift/Ctrl multi-select
    listbox.pack(fill="both", expand=True)
    lsb.config(command=listbox.yview)

    for p in completed_paths:
        listbox.insert(tk.END, "  " + os.path.basename(p))
    if completed_paths:
        listbox.selection_set(0)

    # hint for multi-select
    tk.Label(d, text="Shift-click or Ctrl-click to select multiple files (for Towns Video)",
             font=("segoe UI",7), bg=C["bg"], fg=C["dim"]).pack(padx=16, anchor="w", pady=(0,4))

    def _get_selection(single=False):
        """Return list of selected paths, or show warning if nothing selected."""
        sel = listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Please select at least one file.", parent=d)
            return []
        paths = [completed_paths[i] for i in sel]
        if single and len(paths) > 1:
            messagebox.showwarning("Single file only",
                                   "Cache Editor opens one file at a time.\nPlease select a single file.",
                                   parent=d)
            return []
        return paths

    def _find_script(candidates):
        for c in candidates:
            p = os.path.join(SCRIPT_DIR, c)
            if os.path.exists(p):
                return p
        return None

    def _launch(script, args=()):
        import subprocess
        try:
            subprocess.Popen([sys.executable, script] + list(args), cwd=SCRIPT_DIR)
        except Exception as e:
            messagebox.showerror("Launch error", f"Cannot open script:\n{e}", parent=d)

    def _open_in_cache_editor():
        paths = _get_selection(single=True)
        if not paths: return
        script = _find_script(["Cache_Editor.pyw","Cache_Editor.py",
                                "cache_editor.pyw","cache_editor.py"])
        if not script:
            script = filedialog.askopenfilename(
                title="Select Cache Editor", filetypes=[("Python files","*.py *.pyw")], parent=d)
        if not script: return
        _launch(script, ["--gpx", paths[0]])

    def _open_in_towns_video():
        paths = _get_selection(single=False)
        if not paths: return
        script = _find_script(["Towns_video_dx.pyw","Towns_video_dx.py",
                                "towns_video_dx.pyw","towns_video_dx.py",
                                "Towns_video.pyw","Towns_video.py"])
        if not script:
            script = filedialog.askopenfilename(
                title="Select Towns Video script", filetypes=[("Python files","*.py *.pyw")], parent=d)
        if not script: return
        _launch(script, paths)   # pass all selected GPX paths as positional args

    bf = tk.Frame(d, bg=C["bg"]); bf.pack(fill="x", padx=16, pady=(0,12))
    mk_btn(bf, "📂  Open in Cache Editor",  C["blue"],   _open_in_cache_editor).pack(side="left", padx=(0,6))
    mk_btn(bf, "🎬  Open in Towns Video",   C["orange"], _open_in_towns_video).pack(side="left", padx=(0,6))
    mk_btn(bf, "Close",                     C["dim"],    d.destroy).pack(side="left")
    tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")


def process_files_thread(conn, file_paths, cmt_choice_value, dest_choice_value, start_index=0):
    manual_dest = None
    if dest_choice_value == 3:
        manual_dest = filedialog.askdirectory(title="Select destination folder")
        if not manual_dest:
            messagebox.showwarning("Cancelled", "No destination selected.")
            return
    stop_event.clear()
    pause_event.set()
    processing_state["running"] = True
    completed_paths = []
    for idx, fp in enumerate(file_paths, start=1):
        if not root.winfo_exists(): break
        si = start_index if idx == 1 else 0
        result = process_single_file(conn, fp, cmt_choice_value, dest_choice_value,
                                     manual_dest, idx, len(file_paths), start_index=si)
        if result:
            completed_paths.append(result)
        if stop_event.is_set(): break
    processing_state["running"] = False
    if pause_btn_ref[0]: pause_btn_ref[0].config(text="⏸  Pause")
    if stop_event.is_set():
        stop_event.clear()
        status_label.config(text="Processing stopped.")
    else:
        status_label.config(text="All files processed.")
        if completed_paths:
            root.after(0, show_completion_dialog, completed_paths)

def start_processing_from_button():
    if processing_state["running"]:
        messagebox.showinfo("Processing", "Processing already in progress.")
        return
    files = filedialog.askopenfilenames(title="Select GPX file(s)", filetypes=[("GPX files", "*.gpx")])
    if not files: return
    refresh_cache_count_label()
    t = threading.Thread(target=process_files_thread,
                         args=(db_conn, list(files), cmt_choice.get(), destination_choice.get()),
                         daemon=True)
    processing_state["thread"] = t
    t.start()

start_button.config(command=start_processing_from_button)

def stop_and_save():
    if not processing_state["running"]:
        messagebox.showinfo("Stop", "No active processing.")
        return
    if messagebox.askyesno("Stop & Save", "Stop processing and save what has been geocoded so far?"):
        pause_event.set()
        stop_event.set()
        status_label.config(text="Stopping — saving partial file, please wait…")

# ──────────────────────────────────────────────────────────────────────────────
# Start from Point dialog  (styled to match Ironer dialogs)
# ──────────────────────────────────────────────────────────────────────────────
def open_start_from_point_dialog():
    if processing_state["running"]:
        messagebox.showinfo("Busy", "Processing already in progress.")
        return
    file_path = filedialog.askopenfilename(
        title="Select GPX file to process from a specific point",
        filetypes=[("GPX files", "*.gpx")])
    if not file_path: return

    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            gpx_tmp = gpxpy.parse(fh)
    except Exception as e:
        messagebox.showerror("Parse error", f"Failed to parse GPX:\n{e}")
        return

    points_tmp = [pt for trk in gpx_tmp.tracks for seg in trk.segments for pt in seg.points]
    if not points_tmp:
        messagebox.showwarning("No points", "No trackpoints found in this file.")
        return

    entries = []
    for i, pt in enumerate(points_tmp):
        ts = getattr(pt, "time", None)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "(no timestamp)"
        entries.append(f"#{i+1:05d}   {ts_str}")

    # ── dialog ────────────────────────────────────────────────────────────────
    d = tk.Toplevel(root)
    d.title("Start from Point")
    d.configure(bg=C["bg"])
    d.geometry("520x560")
    d.grab_set()
    d.resizable(False, True)

    tk.Frame(d, bg=C["accent"], height=2).pack(fill="x")
    tk.Label(d, text="START FROM POINT",
             font=("segoe UI",10,"bold"), bg=C["bg"], fg=C["accent"]).pack(padx=16, pady=(12,2), anchor="w")
    tk.Label(d, text=os.path.basename(file_path),
             font=("segoe UI",8,"italic"), bg=C["bg"], fg=C["muted"]).pack(padx=16, anchor="w")
    tk.Label(d, text=f"{len(points_tmp)} trackpoints · select starting point:",
             font=("segoe UI",8), bg=C["bg"], fg=C["dim"]).pack(padx=16, pady=(2,8), anchor="w")
    tk.Frame(d, bg=C["border"], height=1).pack(fill="x", padx=16)

    # filter
    sf = tk.Frame(d, bg=C["bg"]); sf.pack(fill="x", padx=16, pady=8)
    tk.Label(sf, text="Filter:", font=("segoe UI",8), bg=C["bg"],
             fg=C["muted"]).pack(side="left", padx=(0,6))
    search_var = tk.StringVar()
    se = ttk.Entry(sf, textvariable=search_var, width=36)
    se.pack(side="left")

    # listbox
    lf = tk.Frame(d, bg=C["accent"], padx=1, pady=1)
    lf.pack(fill="both", expand=True, padx=16, pady=(0,8))
    li = tk.Frame(lf, bg=C["panel2"])
    li.pack(fill="both", expand=True)
    lsb = ttk.Scrollbar(li, orient="vertical")
    lsb.pack(side="right", fill="y")
    listbox = tk.Listbox(li, yscrollcommand=lsb.set, font=("segoe UI",8),
                          bg=C["panel2"], fg=C["text"],
                          selectbackground=C["accent"], selectforeground="black",
                          activestyle="none", relief="flat", borderwidth=0,
                          selectmode="single")
    listbox.pack(fill="both", expand=True)
    lsb.config(command=listbox.yview)

    filtered_indices = []
    def populate(filter_str=""):
        listbox.delete(0, tk.END)
        filtered_indices.clear()
        fl = filter_str.lower()
        for i, e in enumerate(entries):
            if fl in e.lower():
                listbox.insert(tk.END, "  " + e)
                filtered_indices.append(i)
        if filtered_indices:
            listbox.selection_set(0)
            listbox.see(0)
    search_var.trace_add("write", lambda *_: populate(search_var.get()))
    populate()

    selected_index = [None]
    def on_ok():
        sel = listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Please select a starting point.", parent=d)
            return
        selected_index[0] = filtered_indices[sel[0]]
        d.destroy()

    bf = tk.Frame(d, bg=C["bg"]); bf.pack(fill="x", padx=16, pady=(0,12))
    mk_btn(bf, "▶  Start from here", C["green"], on_ok).pack(side="left", padx=(0,6))
    mk_btn(bf, "Cancel",             C["dim"],   d.destroy).pack(side="left")
    tk.Frame(d, bg=C["accent"], height=2).pack(fill="x", side="bottom")

    d.wait_window()
    if selected_index[0] is None: return

    refresh_cache_count_label()
    t = threading.Thread(target=process_files_thread,
                         args=(db_conn, [file_path], cmt_choice.get(), destination_choice.get()),
                         kwargs={"start_index": selected_index[0]},
                         daemon=True)
    processing_state["thread"] = t
    t.start()

# ──────────────────────────────────────────────────────────────────────────────
# Initial cache count + close handler
# ──────────────────────────────────────────────────────────────────────────────
try:    refresh_cache_count_label()
except: pass

def on_close():
    try:    db_conn.close()
    except: pass
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # auto-start processing if a GPX path was passed as argv[1]
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        def _auto_start():
            # apply comment format if passed as argv[2]
            if len(sys.argv) > 2:
                try:
                    cmt_choice.set(int(sys.argv[2]))
                except (ValueError, IndexError):
                    pass
            refresh_cache_count_label()
            t = threading.Thread(
                target=process_files_thread,
                args=(db_conn, [sys.argv[1]], cmt_choice.get(), destination_choice.get()),
                daemon=True)
            processing_state["thread"] = t
            t.start()
        root.after(800, _auto_start)   # 800ms lets the splash finish first

    root.mainloop()
