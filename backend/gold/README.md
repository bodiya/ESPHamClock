# HamClock Backend Gold Reference Files

**Retrieved:** 2026-01-31 21:16 UTC
**Source:** clearskyinstitute.com

## Retrying Failed Downloads

The `/maps/` endpoint was returning empty responses when this data was collected.
To retry downloading the missing map files once the server is back online:

```bash
# Preview what would be downloaded
./retry-failed.sh --dry-run

# Actually download the files
./retry-failed.sh
```

The script will:
- Download all map styles (Countries, Terrain, DRAP, Aurora, Weather)
- Download all resolutions (800x480, 1600x960, 2400x1440, 3200x1920)
- Download additional SDO image resolutions (340, 510, 680)
- Skip files that already exist
- Report success/failure counts

## Purpose

These files capture the actual output format of the clearskyinstitute.com backend
as reference for building a replacement. Each endpoint includes both the response
body and HTTP headers in a `.headers` file.

## HTTP Response Format

All responses use HTTP/1.0 with these typical headers:
```
HTTP/1.0 200 Ok
Connection: close
Remote_Addr: {client_ip}
Last-Modified: {timestamp}
Content-Length: {bytes}
```

For dynamic endpoints, `Content-Type: text/plain; charset=ISO-8859-1` is included.
For compressed images: `Content-Type: image/bmp; charset=ISO-8859-1`

## File Format Summary

### Space Weather Data

| File | Format | Example Line |
|------|--------|--------------|
| `ssn/ssn-31.txt` | `YYYY MM DD value` | `2026 01 31 126` |
| `ssn/ssn-history.txt` | `year value` (year as decimal) | `1900 15.7` |
| `solar-flux/solarflux-99.txt` | One float per line | `166` |
| `solar-flux/solarflux-history.txt` | `year value` (year as decimal) | `1947.08 202.75` |
| `geomag/kindex.txt` | One float per line (Kp 0-9) | `4.00` |
| `xray/xray.txt` | `YYYY M D HHMM zeros short_wave long_wave` | `2026  1 30  2013   00000  00000     1.74e-08    8.77e-07` |
| `solar-wind/swind-24hr.txt` | `unix_ts density speed` | `1769804160 1.38 489.9` |
| `Bz/Bz.txt` | `# header` then `unix_ts Bx By Bz Bt` | `1769804760    2.9   -1.3   -1.0    3.3` |
| `NOAASpaceWX/noaaswx.txt` | `{R\|S\|G} today tomorrow day2 day3` | `R  0 0 0 0` |
| `NOAASpaceWX/rank2_coeffs.txt` | `index a b c // comment` | `0       0        0.05    -6` |
| `aurora/aurora.txt` | `unix_ts percent` | `1769808962 23` |
| `dst/dst.txt` | `ISO8601 value` | `2026-01-30T21:00:00 -5` |
| `drap/stats.txt` | `unix_ts : min max mean` | `1769786161 : 0 5.1 1.33556` |

### Amateur Radio Data

| File | Format | Notes |
|------|--------|-------|
| `ONTA/onta.txt` | CSV with header | `#call,Hz,unix,mode,grid,lat,lng,park,org` |
| `contests/contests311.txt` | Attribution line, then pairs | First line: source credit |
| `dxpeds/dxpeditions.txt` | N credit entries, then CSV | First line: count of credit pairs |
| `RSS/web15rss.txt` | `Source: headline` per line | Max 15 lines |
| `fetchPSKReporter_*.txt` | CSV | `unix,tx_grid,tx_call,rx_grid,rx_call,mode,freq_hz,snr` |
| `fetchRBN_bygrid.txt` | CSV | Same format, tx_grid often empty (4 spaces) |
| `fetchWSPR_bygrid.txt` | CSV | Same format as PSK Reporter |

### Propagation

| File | Format | Notes |
|------|--------|-------|
| `fetchBandConditions.txt` | Line 1: zeros, Line 2: params, Lines 3-26: hourly data | `hour reliabilities...` (9 comma-separated values) |
| `fetchVOACAP*.z` | Zlib-compressed BMP | RGB565 format, 320x160 in this sample |

### SDO Solar Images

| File | Description |
|------|-------------|
| `SDO/f_211_193_171_170.bmp.z` | Composite (211/193/171) - 170px for 800x480 |
| `SDO/latest_170_HMIB.bmp.z` | Magnetogram |
| `SDO/latest_170_HMIIC.bmp.z` | 6173A Continuum |
| `SDO/f_131_170.bmp.z` | 131A |
| `SDO/f_193_170.bmp.z` | 193A |
| `SDO/f_211_170.bmp.z` | 211A |
| `SDO/f_304_170.bmp.z` | 304A |

All SDO files are zlib-compressed BMP images. Filename pattern: `{type}_{size}.bmp.z`
Sizes by resolution: 170 (800x480), 340 (1600x960), 510 (2400x1440), 680 (3200x1920)

### Geographic/Reference

| File | Format | Notes |
|------|--------|-------|
| `cities2.txt` | `lat, lng, "description"` | ~3000 cities |
| `cty/cty_wt_mod-ll-dxcc.txt` | `prefix lat lng dxcc` | Begins with # comments |
| `esats/esats.txt` | Standard TLE format | Name, Line1, Line2 triplets |
| `worldwx/wx.txt` | Fixed-width columns with header | lat, lng, temp, hum, wind, dir, pressure, wx, tz |

### Weather

| File | Format |
|------|--------|
| `wx_de.txt` / `wx_dx.txt` | `key=value` pairs, 11 lines |

Keys: city, temperature_c, pressure_hPa, pressure_chg, humidity_percent,
wind_speed_mps, wind_dir_name, clouds, conditions, attribution, timezone

### Misc

| File | Format |
|------|--------|
| `version.txt` | Version on line 1, optional info on line 2 |
| `fetchIPGeoloc.txt` | `KEY=value` format: LAT, LNG, IP, CREDIT |

## Query Parameters Used

### fetchBandConditions.pl
```
?YEAR=2026&MONTH=1&RXLAT=42.36&RXLNG=-71.06&TXLAT=51.51&TXLNG=-0.13&UTC=12&PATH=1&POW=100&MODE=38&TOA=3
```

### fetchVOACAPArea.pl / MUF / TOA
```
?YEAR=2026&MONTH=1&UTC=12&TXLAT=42.36&TXLNG=-71.06&PATH=0&WATTS=100&WIDTH=320&HEIGHT=160&MHZ=14.1&TOA=3&SSN=120&MODE=38
```
Note: SSN parameter is required but not documented in error message examples.

### fetchPSKReporter.pl / fetchWSPR.pl / fetchRBN.pl
```
?bygrid=FN31pr&maxage=3600   # spots BY our grid in last hour
?ofgrid=FN31pr&maxage=3600   # spots OF our grid in last hour
?bycall=W1ABC&maxage=3600    # by callsign
?ofcall=W1ABC&maxage=3600    # of callsign
```

### wx.pl
```
?is_de=1&lat=42.36&lng=-71.06  # DE location weather
?is_de=0&lat=51.51&lng=-0.13   # DX location weather
```

## Notes

- **Map files (`/maps/*.z`) are unavailable** - The server returns empty responses for all
  map styles tested (Countries, Terrain, DRAP, Aurora, Weather). These will need to be
  generated for the replacement backend. Map filenames follow the pattern:
  `map-{D|N}-{width}x{height}-{style}.bmp.z` (e.g., `map-D-800x480-Countries.bmp.z`)
- SDO images successfully retrieved from `/SDO/{filename}.bmp.z`
- All times in responses are Unix timestamps (seconds since 1970)
- Negative timezone values = west of UTC (in seconds)
- pressure_chg=-999 means "no change data available"

## Map Generation Notes

The `/maps/` endpoint serves pre-rendered map images for these styles:
- **Countries** - Political boundaries (static)
- **Terrain** - Topographic elevation (static)
- **DRAP-S** - D-Region Absorption (dynamic, updated every 5 min)
- **MUF-RT** - Real-time MUF (dynamic)
- **Aurora** - Northern/Southern lights forecast (dynamic)
- **Clouds** - Cloud cover overlay (dynamic)
- **Weather** - Temperature/pressure overlay (Wx-mB or Wx-in variants)

Note: MUF-VCAP, TOA, and REL maps are dynamically generated via `fetchVOACAP*.pl`
endpoints, not served from `/maps/`.

Each style has day (D) and night (N) variants. Images are RGB565 BMP format,
zlib-compressed. Base resolution is 800x480, with 2x, 3x, 4x zoom levels available.
