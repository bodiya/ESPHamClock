# HamClock Backend Replacement Design Document

## Overview

This document specifies how to build a replacement backend server for ESPHamClock to replace the retiring clearskyinstitute.com services. It covers all endpoints, their exact data formats, and upstream data sources.

**Current Backend:** `clearskyinstitute.com:80` (HTTP)
**Configuration:** Can be changed via `-b host:port` command-line argument

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Space Weather Endpoints](#space-weather-endpoints)
3. [Propagation Endpoints](#propagation-endpoints)
4. [Amateur Radio Data Endpoints](#amateur-radio-data-endpoints)
5. [Geographic Data Endpoints](#geographic-data-endpoints)
6. [Static Data Endpoints](#static-data-endpoints)
7. [Miscellaneous Endpoints](#miscellaneous-endpoints)
8. [Implementation Recommendations](#implementation-recommendations)

---

## Architecture Overview

### Request Pattern

All requests use HTTP/1.1 GET with a User-Agent header. The client skips HTTP headers until blank line, then reads the response body.

### Caching Strategy

HamClock caches most data locally with age-based invalidation. The backend should include appropriate `Cache-Control` headers but the client doesn't require them.

### Data Lifecycle (Ingest vs Derive)

To serve time-series data correctly at any client start time, the backend separates **ingest** (upstream fetch) from **derive** (HamClock-formatted outputs):

- **Raw store**: Append-only or snapshot files under a local `data_root/raw/` hierarchy.
- **Derived store**: Exact HamClock file formats under `data_root/` (the files served to clients).
- **Ingest jobs** run at upstream cadence (minutes → hours).
- **Derive jobs** run at client cadence (often 1–10 minutes) so outputs are always aligned to “now”.

A **datasource registry** declares for each source:

- ingest function, derive function
- ingest schedule, derive schedule
- raw paths, derived paths
- expected line counts, expected cadence

### Health Checks

A periodic health check logs warnings when:

- derived files are missing or stale
- line counts are below expected
- time-series cadence is off (where timestamps are present)

This is designed to catch gaps before the client reports “data invalid”.

### Error Handling

On network errors or malformed responses, HamClock logs to serial console and retries later. Return HTTP 200 with valid data, or let the connection fail - don't return error pages.

---

## Space Weather Endpoints

### 1. Sunspot Number: `/ssn/ssn-31.txt`

**Purpose:** 31 days of sunspot numbers for trend display

**Response Format:**
```
{value1}
{value2}
...
{value31}
```

One float per line, 31 lines total. Oldest first, newest last.

**Upstream Source:** NOAA SWPC
- URL: `https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json`
- Extract `ssn` field from last 31 daily entries
- Alternative: `https://services.swpc.noaa.gov/text/daily-solar-indices.txt`

**Update Frequency:** Daily

---

### 2. Solar Flux: `/solar-flux/solarflux-99.txt`

**Purpose:** 10.7cm radio flux history and predictions

**Response Format:**
```
{value1}
{value2}
...
{value99}
```

One float per line, 99 lines total. Historical + predicted values.

**Upstream Source:** NOAA SWPC
- URL: `https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json`
- Also: `https://services.swpc.noaa.gov/text/daily-solar-indices.txt`
- 27-day outlook: `https://services.swpc.noaa.gov/text/27-day-outlook.txt`

**Update Frequency:** Daily

---

### 3. Kp Index: `/geomag/kindex.txt`

**Purpose:** Geomagnetic disturbance index history and forecast

**Response Format:**
```
{value1}
{value2}
...
```

One float per line (Kp values 0-9). Number of lines defined by `KP_NV` constant.

**Upstream Source:** NOAA SWPC
- Real-time: `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json`
- Forecast: `https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json`
- Alternative: GFZ Potsdam `https://www-app3.gfz-potsdam.de/kp_index/`

**Update Frequency:** Every 3 hours (Kp is 3-hourly index)

---

### 4. X-Ray Flux: `/xray/xray.txt`

**Purpose:** Solar X-ray flux for flare monitoring

**Response Format:**
```
2 {date} {time} ... {short_wavelength_at_col35} ... {long_wavelength_at_col47} ...
2 {date} {time} ... {short_wavelength_at_col35} ... {long_wavelength_at_col47} ...
...
```

Lines starting with `2`, minimum 56 characters. Values at fixed column positions:
- Column 35: Short wavelength intensity (0.05-0.4 nm)
- Column 47: Long wavelength intensity (0.1-0.8 nm)

Missing data coded as `-1.00e+05`, replaced with `1e-9` by client.

**Upstream Source:** NOAA SWPC GOES X-ray
- URL: `https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json`
- Fields: `time_tag`, `flux` (short), `flux` (long) from different energy bands

**Update Frequency:** Every 5 minutes

---

### 5. Solar Wind: `/solar-wind/swind-24hr.txt`

**Purpose:** Solar wind density and speed for radio propagation effects

**Response Format:**
```
{unix_timestamp} {density_per_cm3} {speed_km_s}
{unix_timestamp} {density_per_cm3} {speed_km_s}
...
```

Space-separated: unix timestamp (seconds), density (float), speed (float).

**Upstream Source:** NOAA SWPC DSCOVR/ACE
- URL: `https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json`
- Fields: `time_tag`, `density`, `speed`
- Alternative: `https://services.swpc.noaa.gov/json/dscovr/dscovr_plasma_5m.json`

**Update Frequency:** Every 5 minutes

---

### 6. IMF Bz/Bt: `/Bz/Bz.txt`

**Purpose:** Interplanetary magnetic field for geomagnetic coupling

**Response Format:**
```
{unix_timestamp} {Bx} {By} {Bz} {Bt}
{unix_timestamp} {Bx} {By} {Bz} {Bt}
...
```

Space-separated values. Client uses only Bz and Bt (ignores Bx, By).

**Upstream Source:** NOAA SWPC DSCOVR
- URL: `https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json`
- Fields: `time_tag`, `bx_gsm`, `by_gsm`, `bz_gsm`, `bt`
- Alternative: `https://services.swpc.noaa.gov/json/dscovr/dscovr_mag_5m.json`

**Update Frequency:** Every 5 minutes

---

### 7. NOAA Space Weather Scales: `/NOAASpaceWX/noaaswx.txt`

**Purpose:** Current R (radio), S (solar radiation), G (geomagnetic) storm levels

**Response Format:**
```
R {today} {tomorrow} {day2} {day3}
S {today} {tomorrow} {day2} {day3}
G {today} {tomorrow} {day2} {day3}
```

Exactly 3 lines. First character must be R, S, or G. Four integer values (0-5 scale).

**Upstream Source:** NOAA SWPC
- URL: `https://services.swpc.noaa.gov/products/noaa-scales.json`
- Contains current and forecast R, S, G values

**Update Frequency:** Every hour

---

### 8. Aurora Forecast: `/aurora/aurora.txt`

**Purpose:** Aurora activity percentage for display

**Response Format:**
```
{unix_timestamp} {percent}
{unix_timestamp} {percent}
...
```

Space-separated: unix timestamp, activity percentage (float).

**Upstream Source:** NOAA SWPC
- URL: `https://services.swpc.noaa.gov/json/ovation_aurora_latest.json`
- Alternative: `https://services.swpc.noaa.gov/products/aurora-30-minute-forecast.json`

**Update Frequency:** Every 30 minutes

---

### 9. Dst Index: `/dst/dst.txt`

**Purpose:** Ring current strength for geomagnetic storm intensity

**Response Format:**
```
{ISO8601_datetime} {value}
{ISO8601_datetime} {value}
...
```

ISO8601 format (e.g., `2025-04-15T00:00:00`), space, integer Dst value.

**Upstream Source:** Kyoto WDC
- Real-time: `https://wdc.kugi.kyoto-u.ac.jp/dst_realtime/`
- Provisional: `https://wdc.kugi.kyoto-u.ac.jp/dst_provisional/`
- Format documentation: `https://wdc.kugi.kyoto-u.ac.jp/dstdir/`

**Update Frequency:** Hourly

---

### 10. D-RAP Statistics: `/drap/stats.txt`

**Purpose:** D-Region absorption affecting HF propagation

**Response Format:**
```
{unix_timestamp} : {min} {max} {mean}
{unix_timestamp} : {min} {max} {mean}
...
```

Colon-separated timestamp and space-separated min/max/mean floats.

**Upstream Source:** NOAA SWPC D-RAP
- URL: `https://services.swpc.noaa.gov/products/animations/d-rap/latest.json`
- Alternative: Parse D-RAP maps for statistics

**Update Frequency:** Every 15 minutes

---

### 11. Space Weather Ranking Coefficients: `/NOAASpaceWX/rank2_coeffs.txt`

**Purpose:** Coefficients for calculating space weather severity ranking

**Response Format:**
```
0 {a0} {b0} {c0}
1 {a1} {b1} {c1}
...
```

Index (must match line number), then three float coefficients.
Formula: `rank = (a*value + b)*value + c`

**Upstream Source:** Static/derived data
- These appear to be calibration constants defined by the original author
- May need to reverse-engineer from existing behavior or use sensible defaults

**Update Frequency:** Static (rarely changes)

---

## Propagation Endpoints

### 12. Band Conditions: `/fetchBandConditions.pl`

**Purpose:** VOACAP propagation predictions for amateur bands

**Query Parameters:**
```
?YEAR={year}&MONTH={month}&RXLAT={lat}&RXLNG={lng}&TXLAT={lat}&TXLNG={lng}&UTC={hour}&PATH={path}&POW={power}&MODE={mode}&TOA={angle}
```

- `PATH`: 1=short, 2=long
- `POW`: 1, 5, 10, 50, 100, 500, 1000 watts
- `MODE`: 19=CW, 22=RTTY, 38=SSB, 49=AM, 3=WSPR, 13=FT8, 17=FT4
- `TOA`: Take-off angle in degrees

**Response Format:**
```
{config_summary_line}
{utc_hour} {rel80},{skip},{rel40},{rel30},{rel20},{rel17},{rel15},{rel10}
{utc_hour} {rel80},{skip},{rel40},{rel30},{rel20},{rel17},{rel15},{rel10}
...
```

Line 1: Configuration summary text (displayed to user).
Lines 2-25: 24 lines of hourly data. First field is UTC hour (1-24), then 8 comma-separated reliability values (0.0-1.0). Second value is skipped (60m band not used).

**Upstream Source:** VOACAP
- **IMPORTANT:** Automated access to voacap.com is prohibited without permission
- Options:
  1. Run VOACAP locally using `voacapl` (Linux) or Windows VOACAP
  2. Use ITURHFProp as alternative (open source)
  3. Pre-compute and cache common path combinations
- Software: https://www.voacap.com/
- Python wrapper: https://github.com/jawatson/pythonprop

**Update Frequency:** Hourly (predictions change with time)

---

### 13. VOACAP Area Map: `/fetchVOACAPArea.pl`

**Purpose:** Geographic propagation coverage maps

**Query Parameters:**
```
?YEAR={year}&MONTH={month}&UTC={hour}&TXLAT={lat}&TXLNG={lng}&PATH={path}&WATTS={power}&WIDTH={pixels}&HEIGHT={pixels}&MHZ={freq}&MODE={mode}
```

**Response Format:** Zlib-compressed BMP image
- Content-Length header indicates compressed size
- Decompresses to RGB565 BMP V4 format

**Upstream Source:** VOACAP (same restrictions as band conditions)

**Update Frequency:** Hourly

---

### 14. MUF Map: `/fetchVOACAP-MUF.pl`

**Purpose:** Maximum Usable Frequency map

**Query/Response:** Same format as VOACAP Area Map

---

### 15. Take-Off Angle Map: `/fetchVOACAP-TOA.pl`

**Purpose:** Optimal take-off angle map

**Query/Response:** Same format as VOACAP Area Map

---

## Amateur Radio Data Endpoints

### 16. PSK Reporter: `/fetchPSKReporter.pl`

**Purpose:** Digital mode reception reports

**Query Parameters:**
```
?{of|by}{call|grid}={identifier}&maxage={seconds}
```

Examples:
- `?bygrid=FN31&maxage=1800` - Reports BY our grid in last 30 min
- `?ofcall=W1ABC&maxage=3600` - Reports OF callsign in last hour

**Response Format:**
```
{unix_time},{tx_grid},{tx_call},{rx_grid},{rx_call},{mode},{freq_hz},{snr}
{unix_time},{tx_grid},{tx_call},{rx_grid},{rx_call},{mode},{freq_hz},{snr}
...
```

Comma-separated fields. Grid is 6-char Maidenhead, call max 11 chars, mode max 7 chars.

**Upstream Source:** PSK Reporter
- URL: `https://pskreporter.info/cgi-bin/pskquery5.pl`
- Query format: `?flowStartSeconds=-{seconds}&rronly=1&...`
- Returns XML, needs transformation to CSV
- No API key required

**Update Frequency:** Every few minutes

---

### 17. WSPR Spots: `/fetchWSPR.pl`

**Purpose:** Weak signal propagation reports

**Query/Response:** Same format as PSK Reporter

**Upstream Source:** WSPRnet
- URL: `https://wsprnet.org/olddb`
- Database queries available
- No API key required

**Update Frequency:** Every few minutes

---

### 18. Reverse Beacon Network: `/fetchRBN.pl`

**Purpose:** CW/RTTY skimmer spots

**Query/Response:** Same format as PSK Reporter

**Upstream Source:** Reverse Beacon Network
- Telnet: `telnet.reversebeacon.net:7000`
- Web: `https://www.reversebeacon.net/spots.php`
- No API key required

**Update Frequency:** Real-time (aggregate every few minutes)

---

### 19. On The Air (POTA/SOTA): `/ONTA/onta.txt`

**Purpose:** Current park and summit activators

**Response Format:**
```
{call},{freq_hz},{unix_time},{mode},{grid},{lat},{lng},{activation_id},{program}
{call},{freq_hz},{unix_time},{mode},{grid},{lat},{lng},{activation_id},{program}
...
```

Comma-separated. Program is "POTA" or "SOTA". Mode may be empty.

**Upstream Sources:**

POTA:
- URL: `https://api.pota.app/spot/activator`
- Returns JSON array of current activations
- No API key required

SOTA:
- URL: `https://api-db2.sota.org.uk/api/spots`
- Requires authentication (client ID, credentials)
- Contact SOTA organization for API access

**Update Frequency:** Every 5 minutes

---

### 20. Contests: `/contests/contests311.txt`

**Purpose:** Upcoming amateur radio contests

**Response Format:**
```
{credit_line}
{unix_start} {unix_end} {title}
{url}
{unix_start} {unix_end} {title}
{url}
...
```

Line 1: Attribution/credit string.
Subsequent lines: Pairs of (start/end/title) and (url).

**Upstream Sources:**
- WA7BNM Contest Calendar: `https://www.contestcalendar.com/contestcal.html`
- NG3K: `https://www.ng3k.com/Contest/`
- ARRL: `https://www.arrl.org/contest-calendar`

All require HTML scraping - no structured API available.

**Update Frequency:** Daily

---

### 21. DXpeditions: `/dxpeds/dxpeditions.txt`

**Purpose:** Upcoming and active DXpeditions

**Response Format:**
```
{num_credit_lines}
{credit_name_1}
{credit_url_1}
{credit_name_2}
{credit_url_2}
...
{unix_start},{unix_end},{location},{callsign},{url}
{unix_start},{unix_end},{location},{callsign},{url}
...
```

First line: Number of credit entries (N).
Next 2N lines: Credit name/URL pairs.
Remaining lines: CSV of dxpedition data.

**Upstream Sources:**
- NG3K ADXO: `https://www.ng3k.com/misc/adxo.html`
- DX-World: `https://www.dx-world.net/`
- 425DX News: `https://www.425dxn.org/`

All require HTML scraping.

**Update Frequency:** Daily

---

### 22. RSS Feed: `/RSS/web15rss.pl`

**Purpose:** Ham radio news headlines

**Response Format:**
```
{headline1}
{headline2}
...
```

Plain text, one headline per line, max 15 lines.

**Upstream Sources:**
- ARRL News: `http://www.arrl.org/arrl.rss`
- eHam News: `https://www.eham.net/rss/news`
- DX-World: RSS feed
- QRZ News: RSS feed

Aggregate multiple feeds, extract titles.

**Update Frequency:** Hourly

---

## Geographic Data Endpoints

### 23. IP Geolocation: `/fetchIPGeoloc.pl`

**Purpose:** Initial location setup from IP address

**Query Parameters:** `?IP={ip}` (optional, uses client IP if omitted)

**Response Format:**
```
LAT={latitude}
LNG={longitude}
IP={ip_address}
CREDIT={attribution}
```

**Upstream Sources:**
- ip-api.com: `http://ip-api.com/json/{ip}` (free, 45 req/min)
- ipapi.co: `https://ipapi.co/{ip}/json/` (1000/day free)
- ipwhois.io: `https://ipwhois.io/json/{ip}` (10000/month free)

All return JSON with lat/lon fields.

**Update Frequency:** On-demand only

---

### 24. Weather: `/wx.pl`

**Purpose:** Current weather for DE/DX locations

**Query Parameters:** `?is_de={0|1}&lat={latitude}&lng={longitude}`

**Response Format:**
```
city=City Name
temperature_c=22.5
pressure_hPa=1013.25
pressure_chg=0.5
humidity_percent=65
wind_speed_mps=5.2
wind_dir_name=NE
clouds=Partly Cloudy
conditions=Clear
attribution=Source Name
timezone=1
```

Exactly 11 name=value lines.

**Upstream Sources:**
- Open-Meteo (recommended, no API key): `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current_weather=true`
- OpenWeatherMap: `https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={key}`

**Notes:**
- Only Open-Meteo `/v1/forecast` (and `/v1/reverse` for reverse geocoding) are required. Advanced Open-Meteo APIs (Satellite Radiation, Climate, Seasonal Forecast, Ensemble, Historical, Historical Forecast, Previous Model Runs) are not used by any current or planned endpoints.
- The Open-Meteo Standard subscription ($30/month) is sufficient for current usage.

**Update Frequency:** Every 55 minutes

---

### 25. World Weather Grid: `/worldwx/wx.txt`

**Purpose:** Global weather grid for cursor roaming

**Response Format:**
```
{lat} {lng} {temp_C} {humidity_%} {wind_mps} {wind_dir_deg} {pressure_hPa} {conditions} {timezone}

{lat} {lng} {temp_C} {humidity_%} {wind_mps} {wind_dir_deg} {pressure_hPa} {conditions} {timezone}
...
```

Blank line separates longitude blocks. Latitude-major ordering.

**Upstream Source:** Open-Meteo grid API
- Can query multiple points: `https://api.open-meteo.com/v1/forecast?latitude={lat1},{lat2}&longitude={lng1},{lng2}&current_weather=true`

**Notes:**
- Uses Open-Meteo `/v1/forecast` only. No advanced Open-Meteo APIs are required for the grid.
- The Open-Meteo Standard subscription ($30/month) is sufficient for current usage.

**Update Frequency:** Every 45 minutes

---

### 26. Cities: `/cities2.txt`

**Purpose:** City database for location selection

**Response Format:**
```
{latitude}, {longitude}, "{city_name}"
{latitude}, {longitude}, "{city_name}"
...
```

**Upstream Source:** GeoNames
- URL: `https://download.geonames.org/export/dump/cities15000.zip`
- Contains cities with population > 15,000
- Fields: name, lat, lng, country, population

**Update Frequency:** Monthly (static data)

---

### 27. Country/Prefix Data: `/cty/cty_wt_mod-ll-dxcc.txt`

**Purpose:** Callsign prefix to location/DXCC mapping

**Response Format:**
```
{prefix} {latitude} {longitude} {dxcc_number}
{prefix} {latitude} {longitude} {dxcc_number}
...
```

Skip blank lines and comments (starting with `#`).

**Upstream Source:** AD1C's cty.dat
- URL: `https://www.country-files.com/big-cty/`
- Download: `https://www.country-files.com/cty/cty.dat`
- Needs transformation to add lat/lng from zone data

**Update Frequency:** Monthly

---

## Static Data Endpoints

### 28. Satellite TLEs: `/esats/esats.txt`

**Purpose:** Orbital elements for satellite tracking

**Response Format:**
```
{satellite_name}
{tle_line_1}
{tle_line_2}
{satellite_name}
{tle_line_1}
{tle_line_2}
...
```

Standard TLE format. Spaces in names converted to underscores.

**Upstream Source:** CelesTrak
- Amateur satellites: `https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle`
- Weather satellites: `https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle`
- ISS: `https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle`

**Update Frequency:** Every 2-3 hours (TLEs decay)

---

### 29. Map Tiles: `/maps/{filename}.z`

**Purpose:** Background map images

**Response Format:** Zlib-compressed BMP
- RGB565 format, BMP V4 header
- Multiple zoom levels/styles

**Source:** These are pre-rendered image files
- Must be generated or obtained from original source
- Countries, terrain, ocean maps
- Consider contacting amateur radio community for assets

**Update Frequency:** Static

---

### 30. SDO Solar Images: `/SDO/{filename}.z`

**Purpose:** Solar disk imagery

**Response Format:** Zlib-compressed BMP

**Upstream Source:** NASA SDO (direct, not via backend)
- The client also fetches directly from `https://sdo.gsfc.nasa.gov/`
- Backend provides pre-processed/cached versions

**Update Frequency:** Daily

---

### 31. Version Check: `/version.pl`

**Purpose:** Check for software updates

**Response Format:**
```
{version}
```

Single line with version number (e.g., `4.22` or `4.22b5` for beta).

**Source:** Maintain manually based on current HamClock release

**Update Frequency:** On new releases

---

## Implementation Recommendations

### Recommended Technology Stack

1. **Web Server:** nginx or Caddy for static files + reverse proxy
2. **API Server:** Python (Flask/FastAPI) or Node.js
3. **Scheduler:** Python scheduler (APScheduler) for ingest/derive jobs
4. **Cache:** local filesystem cache (raw + derived)
5. **Storage:** local disk (no external object storage required)

### Directory Structure

```
/
├── raw/
│   ├── aurora/
│   │   ├── source.txt
│   │   ├── hemi-power.txt
│   │   └── ovation.json
│   └── xray/
│       └── xrays-7-day.json
├── Bz/
│   └── Bz.txt
├── solar-wind/
│   └── swind-24hr.txt
├── ssn/
│   └── ssn-31.txt
├── solar-flux/
│   └── solarflux-99.txt
├── geomag/
│   └── kindex.txt
├── xray/
│   └── xray.txt
├── NOAASpaceWX/
│   ├── noaaswx.txt
│   └── rank2_coeffs.txt
├── aurora/
│   └── aurora.txt
├── dst/
│   └── dst.txt
├── drap/
│   └── stats.txt
├── cty/
│   └── cty_wt_mod-ll-dxcc.txt
├── maps/
│   └── *.z
├── SDO/
│   └── *.z
├── contests/
│   └── contests311.txt
├── dxpeds/
│   └── dxpeditions.txt
├── ONTA/
│   └── onta.txt
├── esats/
│   └── esats.txt
├── RSS/
│   └── web15rss.pl (dynamic)
├── worldwx/
│   └── wx.txt
├── cities2.txt
├── version.pl (dynamic)
├── fetchBandConditions.pl (dynamic)
├── fetchIPGeoloc.pl (dynamic)
├── fetchPSKReporter.pl (dynamic)
├── fetchWSPR.pl (dynamic)
├── fetchRBN.pl (dynamic)
├── fetchVOACAPArea.pl (dynamic)
├── fetchVOACAP-MUF.pl (dynamic)
├── fetchVOACAP-TOA.pl (dynamic)
└── wx.pl (dynamic)
```

### Update Schedule

Use separate schedules for **ingest** (upstream fetch) and **derive** (HamClock output):

| Frequency | Endpoints |
|-----------|-----------|
| 1 minute | xray derive |
| 5 minutes | xray ingest, solar-wind, Bz |
| 15 minutes | drap |
| 30 minutes | aurora ingest/derive |
| 1 hour | ssn, solarflux, kindex, noaaswx, contests, RSS |
| 3 hours | esats, dst |
| Daily | dxpeds, cities, cty |
| Static | maps, rank2_coeffs |

### Backend Implementation Notes

- **Base path:** Serve under `/ham/HamClock` by default; allow configuration via `--base-path`.
- **Startup refresh:** `--refresh-on-start` runs ingest then derive for all sources.
- **Single-source update:** `--update-x-on-start name[:ingest|:derive]`.
- **Fallback proxy:** Optional `--clearskyinstitute-fallback` with `--fallback-redirect` to issue 302 Location for unimplemented endpoints. Fallback responses are logged in full when enabled.
- **Reverse geocode cache:** Local cache with long TTL; Nominatim or configurable provider.
- **Propagation engine:** Optional ITURHFProp CLI integration; set path and data directory via config/environment.

### Priority Implementation Order

1. **Phase 1 - Critical (get HamClock running):**
   - `/fetchIPGeoloc.pl`
   - `/cty/cty_wt_mod-ll-dxcc.txt`
   - `/cities2.txt`
   - `/esats/esats.txt`
   - `/version.pl`

2. **Phase 2 - Space Weather:**
   - All `/ssn/`, `/solar-flux/`, `/geomag/`, `/xray/` endpoints
   - `/Bz/`, `/solar-wind/`, `/aurora/`, `/dst/`
   - `/NOAASpaceWX/`

3. **Phase 3 - Amateur Radio Data:**
   - `/fetchPSKReporter.pl`, `/fetchWSPR.pl`, `/fetchRBN.pl`
   - `/ONTA/onta.txt`
   - `/contests/`, `/dxpeds/`

4. **Phase 4 - Weather:**
   - `/wx.pl`
   - `/worldwx/wx.txt`

5. **Phase 5 - Propagation (most complex):**
   - `/fetchBandConditions.pl`
   - `/fetchVOACAPArea.pl`, etc.
   - `/drap/stats.txt`

6. **Phase 6 - Static Assets:**
   - `/maps/*.z`
   - `/SDO/*.z`

### Client Modification

To use a new backend, either:

1. Launch with `-b newbackend.example.com:80`
2. Or modify `wifi.cpp` line 8:
   ```cpp
   static const char backend_host[] = "newbackend.example.com";
   ```

### Testing

Each endpoint can be tested independently:
```bash
curl -v "http://localhost:8080/ssn/ssn-31.txt"
curl -v "http://localhost:8080/fetchIPGeoloc.pl?IP=8.8.8.8"
curl -v "http://localhost:8080/wx.pl?is_de=1&lat=42.0&lng=-71.0"
```

Compare output format against this specification.
