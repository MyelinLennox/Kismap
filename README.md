# KISMAP

A local web map for [Kismet](https://www.kismetwireless.net/) SQLite captures (.kismet). KISMAP maps GPS data and estimates AP locations from RSSI data with filtering tools for research and investigation.

**KISMAP does not capture wirelesss data. Do not use for mapping unauthorized devices.**

## Features

- Load Kismet or SQLite databases into an interactive web-based interface.
- Map GPS observations with Leaflet and OpenStreetMap.
- Filter by band, date, table, and database columns.
- Select all BSSIDs, specific BSSIDs or restrict data with a BSSID allowlist.
- Estimate AP locations from RSSI.
- Calibrate path loss from a known AP location.
- Show device labels and signal heatmaps.
- Export visible records as CSV.

## Requirements

- Python 3.9+
- A Kismet SQLite database with GPS observations
- Browser internet access for map assets and tiles

Python dependencies are listed in [requirements.txt](./requirements.txt).

## Input database

The app reads a Kismet SQLite database. The main packet data comes from the `packets` table and uses these fields:

- `lat`, `lon`: capture coordinates
- `signal`: RSSI/signal value
- `frequency`: channel frequency
- `sourcemac`: BSSID
- `ts_sec`: Unix timestamp

Rows without valid coordinates, signal values, BSSIDs, or timestamps are ignored. Coordinates at `0,0` are also ignored. Other tables with `lat` and `lon` columns can appear on the map when their data matches the selected BSSIDs.


## Installation

Install:

```powershell
git clone https://github.com/MyelinLennox/Kismap.git
cd Kismap
python -m venv .venv
\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

## Commands

Windows:

```powershell
python kismap_web.py
```

Linux/macOS:

```bash
python3 kismap_web.py
```

Headless Linux:

```bash
python3 kismap_web.py --no-browser
```

Custom host and port:

```bash
python3 kismap_web.py --host 0.0.0.0 --port 8080 --no-browser
```

Load a database at startup:

```bash
python3 kismap_web.py --input ./captures/field-test.kismet --no-browser
```

Set startup options directly:

```bash
python3 kismap_web.py --input ./captures/field-test.kismet --cell-size 5 --path-loss 2.5
```

Help:

```bash
python3 kismap_web.py --help
```

The app will host itself on a local URL. Open the output in a browser, then use the **Data** tab to select a database. If `--input` is used, the database loads at startup.

Options:

- `--host HOST`: bind address. Default: `127.0.0.1`.
- `--port PORT`: TCP port. Default: `0` (automatic).
- `--no-browser`: do not open a browser.
- `--browser`: open a browser, including when the config file disables it.
- `--input PATH`: load a Kismet database at startup.
- `--cell-size METERS`: default estimate cell size. Range: `0` to `1000`.
- `--path-loss VALUE`: default path-loss exponent. Range: `0` to `10`.
- `--allowlist BSSID ...`: load only the listed BSSIDs.
- `--config PATH`: load settings from a JSON file.

Stop the server with `Ctrl+C`.

The same options work with `kismap.py`:

```bash
python3 kismap.py --no-browser
```

### JSON configuration

Example `config.json`:

```json
{
  "input": "./captures/field-test.kismet",
  "host": "127.0.0.1",
  "port": 8080,
  "browser": false,
  "cell_size": 5,
  "path_loss": 2.5,
  "allowlist": ["AA:BB:CC:DD:EE:FF"]
}
```

Run it with:

```bash
python3 kismap_web.py --config config.json
```

Use direct CLI options with `--config` to override values from the JSON file. The app does not delete a database supplied with `--input` or in the config file.

## Interface workflow

1. Start the server.
2. Open the printed URL.
3. Open **Data** tab and load a Kismet database.
4. Select all BSSIDs or add individual BSSIDs.
5. Use **Filters** to narrow the visible records.
6. Use **Tools** for estimates, calibration, heatmaps, device labels, and CSV export.

The database is uploaded to the local Python server and stored in a temporary file. It is removed when the server exits.

## Position estimation

For best position estimates:

1. Use observations with valid latitude and longitude values.
2. Select a BSSID with captures around the AP.
3. Adjust cell size for capture density.
4. Calibrate when the AP location is known.
5. Check RMSE and angular coverage.

At least six distinct cells are required. Default path-loss exponent: `2.5`.

The estimator is a signal model, not a survey replacement. Results depend on GPS accuracy, capture coverage, interference, antenna behavior, and the selected path-loss exponent. A route that stays on one side of an AP may produce a poor estimate. Use RMSE and angular coverage to judge the result.

Calibration for accuracy requires a known AP latitude and longitude. It fits the path-loss exponent for one selected BSSID and uses that value for later estimates in the session.

## Project structure

```text
Kismap/
├── kismap.py          # Data loading, geographic calculations, and estimation
├── kismap_web.py      # Local HTTP server and embedded browser interface
├── requirements.txt   # Python dependencies
└── README.md          # Project documentation
```

`kismap.py` contains the database and estimation logic. `kismap_web.py` contains the local HTTP server and the embedded browser UI.

## Troubleshooting

### The app does not open a browser

Run with `--no-browser`, then open the URL printed in the terminal manually.

### No records appear

Check that the database contains a `packets` table with valid `lat`, `lon`, `signal`, `sourcemac`, and `ts_sec` values. Confirm that an allowlist is not excluding the BSSIDs.

### An estimate needs more capture points

Use more geographically separated captures or increase the cell size. Each selected BSSID needs at least six distinct geographic cells.

### The map has no tiles

The map uses online Leaflet and OpenStreetMap assets. Check browser internet access and follow OpenStreetMap tile usage policies.

## Security and privacy

- Default bind address: `127.0.0.1`.
- Uploaded databases use a temporary file and are removed when the server exits.
- `--host 0.0.0.0` exposes the app to the network. The app has no authentication.

## Map data attribution

The interface uses Leaflet and OpenStreetMap tiles. Follow their attribution and usage policies.