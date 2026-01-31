#!/bin/bash
#
# retry-failed.sh - Retry downloading map files that previously failed
#
# The clearskyinstitute.com /maps/ endpoint was returning empty responses.
# Run this script to retry once the server is back online.
#
# Usage: ./retry-failed.sh [--dry-run]
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BASE_URL="http://clearskyinstitute.com/ham/HamClock"
TIMEOUT=30

# Map styles to download (static maps from /maps/)
# Note: MUF-VCAP, TOA, REL are dynamically generated via fetchVOACAP*.pl
STYLES="Countries Terrain DRAP-S MUF-RT Aurora Clouds"

# Weather maps have unit variants
WX_UNITS="mB in"

# Resolutions (width x height)
RESOLUTIONS="800x480 1600x960 2400x1440 3200x1920"

# Day/Night variants
VARIANTS="D N"

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE - No files will be downloaded ==="
    echo ""
fi

SUCCESS=0
FAILED=0
SKIPPED=0

download_file() {
    local url="$1"
    local outfile="$2"
    local headerfile="$3"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY-RUN] Would download: $url"
        return 0
    fi

    # Skip if file already exists and is non-empty
    if [[ -f "$outfile" && -s "$outfile" ]]; then
        echo "[SKIP] Already exists: $outfile"
        ((SKIPPED++))
        return 0
    fi

    echo -n "[FETCH] $url ... "

    # Create directory if needed
    mkdir -p "$(dirname "$outfile")"

    # Download with headers
    local http_code
    http_code=$(curl -s -w "%{http_code}" \
        --max-time "$TIMEOUT" \
        -D "$headerfile" \
        -o "$outfile" \
        "$url" 2>/dev/null) || true

    # Check if successful
    if [[ "$http_code" == "200" && -s "$outfile" ]]; then
        local size
        size=$(stat -c%s "$outfile" 2>/dev/null || stat -f%z "$outfile" 2>/dev/null)
        echo "OK (${size} bytes)"
        ((SUCCESS++))
        return 0
    else
        echo "FAILED (HTTP $http_code)"
        rm -f "$outfile" "$headerfile"
        ((FAILED++))
        return 1
    fi
}

echo "=== Retrying Failed Map Downloads ==="
echo "Base URL: $BASE_URL"
echo "Timeout: ${TIMEOUT}s"
echo ""

# Create maps directory
mkdir -p maps

# Download standard map styles
echo "--- Standard Map Styles ---"
for res in $RESOLUTIONS; do
    for style in $STYLES; do
        for variant in $VARIANTS; do
            filename="map-${variant}-${res}-${style}.bmp.z"
            download_file \
                "${BASE_URL}/maps/${filename}" \
                "maps/${filename}" \
                "maps/${filename%.z}.headers"
        done
    done
done

# Download weather maps (with unit variants)
echo ""
echo "--- Weather Map Styles ---"
for res in $RESOLUTIONS; do
    for units in $WX_UNITS; do
        for variant in $VARIANTS; do
            filename="map-${variant}-${res}-Wx-${units}.bmp.z"
            download_file \
                "${BASE_URL}/maps/${filename}" \
                "maps/${filename}" \
                "maps/${filename%.z}.headers"
        done
    done
done

# Download additional SDO resolutions if needed
echo ""
echo "--- Additional SDO Resolutions ---"
SDO_TYPES="f_211_193_171 latest_HMIB latest_HMIIC f_131 f_193 f_211 f_304"
SDO_SIZES="340 510 680"  # Already have 170

for size in $SDO_SIZES; do
    for type in $SDO_TYPES; do
        filename="${type}_${size}.bmp.z"
        download_file \
            "${BASE_URL}/SDO/${filename}" \
            "SDO/${filename}" \
            "SDO/${filename%.z}.headers"
    done
done

# Download history files (for historical plots)
echo ""
echo "--- History Data Files ---"
download_file \
    "${BASE_URL}/ssn/ssn-history.txt" \
    "ssn/ssn-history.txt" \
    "ssn/ssn-history.headers"

download_file \
    "${BASE_URL}/solar-flux/solarflux-history.txt" \
    "solar-flux/solarflux-history.txt" \
    "solar-flux/solarflux-history.headers"

echo ""
echo "=== Summary ==="
echo "Success: $SUCCESS"
echo "Failed:  $FAILED"
echo "Skipped: $SKIPPED"
echo ""

if [[ $FAILED -gt 0 ]]; then
    echo "Some downloads failed. The server may still be having issues."
    echo "Try again later with: $0"
    exit 1
else
    echo "All downloads completed successfully!"
    exit 0
fi
