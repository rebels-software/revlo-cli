#!/bin/bash
#
# Download KiCad Open-Source Hardware Projects
# All repos + branches verified Feb 2026
# Usage: chmod +x download_kicad_projects.sh && ./download_kicad_projects.sh
#

OUTDIR="./kicad_projects"
mkdir -p "$OUTDIR"

# ──────────────────────────────────────────────────
#  category | owner/repo | branch | description
# ──────────────────────────────────────────────────
REPOS=(
  # ── STM32 ──────────────────────────────────
  "STM32|WeActStudio/WeActStudio.MiniSTM32F4x1|master|STM32F401/F411 BlackPill dev board"
  "STM32|mcauser/WEACT_F411CEU6|master|STM32F411 WeAct board KiCad files"
  "STM32|watterott/SilentStepStick|master|TMC stepper driver, STM32-related motor control"

  # ── nRF (Nordic BLE) ───────────────────────
  "nRF|joric/nrfmicro|main|nRF52840 Pro Micro replacement for keyboards"
  "nRF|electronut/ElectronutLabs-Bluey|master|nRF52832 dev board with sensors"
  "nRF|davidphilipbarr/Sweep|main|Minimal split keyboard with nRF support"

  # ── RP2040 (Raspberry Pi) ──────────────────
  "RP2040|joshajohnson/sea-picro|master|RP2040 Pro Micro compatible board"
  "RP2040|adafruit/Adafruit-Feather-RP2040-PCB|main|Adafruit Feather RP2040"
  "RP2040|adafruit/Adafruit-KB2040-PCB|main|Adafruit KB2040 (RP2040 keyboard dev)"
  "RP2040|sparkfun/SparkFun_Thing_Plus-RP2040|main|SparkFun Thing Plus RP2040"

  # ── Arduino / ATmega ───────────────────────
  "Arduino|adafruit/Adafruit-Feather-32u4-Basic-Proto-PCB|master|Adafruit Feather 32u4 Proto"
  "Arduino|sparkfun/Arduino_Pro_Mini_328|master|SparkFun Arduino Pro Mini 328"
  "Arduino|adafruit/Adafruit-ItsyBitsy-32u4-PCB|master|Adafruit ItsyBitsy 32u4"

  # ── General / ESP32 / Mixed ────────────────
  "General|OLIMEX/ESP32-DevKit-LiPo|master|Olimex ESP32 DevKit with LiPo"
  "General|OLIMEX/ESP32-POE|master|Olimex ESP32 with Power-over-Ethernet"
  "General|OLIMEX/ESP32-S2-DevKit-Lipo|main|Olimex ESP32-S2 DevKit"
  "General|adafruit/Adafruit-QT-Py-PCB|master|Adafruit QT Py (SAMD21 tiny board)"
  "General|adafruit/Adafruit-ItsyBitsy-nRF52840-Express-PCB|master|Adafruit ItsyBitsy nRF52840"
  "General|sparkfun/SparkFun_Pro_Micro-RP2040|main|SparkFun Pro Micro RP2040"
)

echo "============================================="
echo " KiCad Projects Downloader"
echo " Total: ${#REPOS[@]} repositories"
echo "============================================="
echo ""

SUCCESS=0
FAIL=0

for entry in "${REPOS[@]}"; do
  IFS='|' read -r category repo branch description <<< "$entry"

  name=$(echo "$repo" | cut -d'/' -f2)
  zip_url="https://github.com/${repo}/archive/refs/heads/${branch}.zip"
  dest_dir="${OUTDIR}/${category}"
  dest_file="${dest_dir}/${name}.zip"

  mkdir -p "$dest_dir"

  echo "[$category] $repo ($branch)"
  echo "  -> $description"
  echo "  -> Downloading..."

  http_code=$(curl -sL -o "$dest_file" -w "%{http_code}" "$zip_url")
  if [ "$http_code" = "200" ]; then
    size=$(du -h "$dest_file" | cut -f1)
    echo "  ✓ OK ($size) -> $dest_file"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "  ✗ FAILED (HTTP $http_code) - $zip_url"
    rm -f "$dest_file"
    FAIL=$((FAIL + 1))
  fi
  echo ""
done

echo "============================================="
echo " Done! $SUCCESS succeeded, $FAIL failed"
echo " Files saved to: $OUTDIR/"
echo "============================================="
echo ""
echo "Directory structure:"
find "$OUTDIR" -name "*.zip" | sort
