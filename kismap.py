#!/usr/bin/env python3
"""Data loading and RSSI-based position estimation for Kismap."""

import math
import sqlite3

import numpy as np
import pandas as pd
from scipy.optimize import least_squares


EARTH_RADIUS_M = 6_371_000


def normalize_frequency_mhz(frequency):
    try:
        frequency = float(frequency)
    except (TypeError, ValueError):
        return float("nan")

    if frequency <= 0:
        return float("nan")
    if frequency > 100_000:
        return frequency / 1000
    if frequency > 100:
        return frequency
    return frequency * 1000


def get_band(frequency):
    mhz = normalize_frequency_mhz(frequency)
    if pd.isna(mhz):
        return "unknown"

    if 2400 <= mhz <= 2500:
        return "2.4"
    if 5150 <= mhz <= 5895:
        return "5"
    if 5925 <= mhz <= 7125:
        return "6"
    return "unknown"


def load_packets(db_path, allowed_bssids):
    """Load AP observations, optionally restricted to an explicit allowlist."""
    bssid_filter = (
        f"AND UPPER(sourcemac) IN ({','.join('?' for _ in allowed_bssids)})"
        if allowed_bssids
        else ""
    )
    query = f"""
        SELECT lat, lon, signal, frequency, sourcemac, ts_sec
        FROM packets
        WHERE lat IS NOT NULL AND lon IS NOT NULL
          AND signal IS NOT NULL AND sourcemac IS NOT NULL
          {bssid_filter}
    """

    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, conn, params=list(allowed_bssids))
    finally:
        conn.close()

    for col in ("lat", "lon", "signal", "frequency", "ts_sec"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["lat", "lon", "signal", "ts_sec"]).copy()
    df = df[
        df["lat"].between(-90, 90)
        & df["lon"].between(-180, 180)
        & (df["signal"] != 0)
        & ~((df["lat"] == 0) & (df["lon"] == 0))
    ].copy()

    df["sourcemac"] = df["sourcemac"].astype(str).str.strip().str.upper()
    df["band"] = df["frequency"].apply(get_band)
    df["time_utc"] = pd.to_datetime(
        df["ts_sec"], unit="s", utc=True, errors="coerce"
    )
    return df.dropna(subset=["time_utc"])


def local_xy(lat, lon, origin_lat, origin_lon):
    x = (
        EARTH_RADIUS_M
        * math.radians(lon - origin_lon)
        * math.cos(math.radians(origin_lat))
    )
    y = EARTH_RADIUS_M * math.radians(lat - origin_lat)
    return x, y


def to_lat_lon(x, y, origin_lat, origin_lon):
    lat = origin_lat + math.degrees(y / EARTH_RADIUS_M)
    lon = origin_lon + math.degrees(
        x / (EARTH_RADIUS_M * math.cos(math.radians(origin_lat)))
    )
    return lat, lon


def aggregate_cells(df, cell_size_m):
    origin_lat = float(df["lat"].median())
    origin_lon = float(df["lon"].median())

    coords = df.apply(
        lambda row: local_xy(row["lat"], row["lon"], origin_lat, origin_lon),
        axis=1,
        result_type="expand",
    )
    coords.columns = ["x", "y"]

    work = df.reset_index(drop=True).copy()
    work[["x", "y"]] = coords.to_numpy()
    work["cell_x"] = np.floor(work["x"] / cell_size_m).astype(int)
    work["cell_y"] = np.floor(work["y"] / cell_size_m).astype(int)

    cells = (
        work.groupby(["cell_x", "cell_y"], as_index=False)
        .agg(
            x=("x", "median"),
            y=("y", "median"),
            signal=("signal", "median"),
            packet_count=("signal", "size"),
        )
    )
    return cells, origin_lat, origin_lon


def estimate_position(cells, origin_lat, origin_lon, path_loss_n):
    """Fit AP x/y and reference RSSI using a robust log-distance model."""
    if len(cells) < 6:
        raise ValueError("At least 6 distinct GPS cells are needed.")

    x = cells["x"].to_numpy(dtype=float)
    y = cells["y"].to_numpy(dtype=float)
    rssi = cells["signal"].to_numpy(dtype=float)

    def residual(params):
        ap_x, ap_y, ref_rssi = params
        distance = np.maximum(np.hypot(x - ap_x, y - ap_y), 1.0)
        predicted = ref_rssi - 10 * path_loss_n * np.log10(distance)
        return predicted - rssi

    # Search around the observation footprint. This assumes the survey route
    # surrounds the AP; it is not appropriate for a route confined to one side.
    pad = max(20.0, 0.1 * max(np.ptp(x), np.ptp(y)))
    x_min, x_max = float(x.min() - pad), float(x.max() + pad)
    y_min, y_max = float(y.min() - pad), float(y.max() + pad)

    best = None
    for start_x in np.linspace(x_min, x_max, 5):
        for start_y in np.linspace(y_min, y_max, 5):
            distances = np.maximum(np.hypot(x - start_x, y - start_y), 1.0)
            ref_start = float(
                np.median(rssi + 10 * path_loss_n * np.log10(distances))
            )

            result = least_squares(
                residual,
                [start_x, start_y, np.clip(ref_start, -100, 40)],
                bounds=([x_min, y_min, -100], [x_max, y_max, 40]),
                loss="soft_l1",
                f_scale=4.0,
                max_nfev=3000,
            )
            if best is None or result.cost < best.cost:
                best = result

    ap_x, ap_y, ref_rssi = best.x
    estimate_lat, estimate_lon = to_lat_lon(ap_x, ap_y, origin_lat, origin_lon)
    errors = residual(best.x)
    rmse = float(np.sqrt(np.mean(errors**2)))

    angles = np.sort(np.degrees(np.arctan2(y - ap_y, x - ap_x)) % 360)
    gaps = np.diff(np.r_[angles, angles[0] + 360])
    angular_coverage = float(360 - gaps.max())

    return {
        "lat": estimate_lat,
        "lon": estimate_lon,
        "ref_rssi": float(ref_rssi),
        "rmse": rmse,
        "angular_coverage": angular_coverage,
    }


def calibrate_path_loss(cells, origin_lat, origin_lon, known_lat, known_lon):
    """Fit path-loss exponent and reference RSSI at a surveyed AP location."""
    if len(cells) < 6:
        raise ValueError("At least 6 distinct GPS cells are needed to calibrate.")

    known_x, known_y = local_xy(known_lat, known_lon, origin_lat, origin_lon)
    distances = np.maximum(
        np.hypot(
            cells["x"].to_numpy(dtype=float) - known_x,
            cells["y"].to_numpy(dtype=float) - known_y,
        ),
        1.0,
    )
    log_distances = np.log10(distances)
    if np.ptp(log_distances) < 0.15:
        raise ValueError(
            "Capture points must span a wider range of distances to calibrate."
        )

    signal = cells["signal"].to_numpy(dtype=float)

    def residual(params):
        reference_rssi, path_loss_n = params
        return reference_rssi - 10 * path_loss_n * log_distances - signal

    initial_reference = float(np.median(signal + 25 * log_distances))
    result = least_squares(
        residual,
        [np.clip(initial_reference, -100, 40), 2.5],
        bounds=([-100, 0.5], [40, 6]),
        loss="soft_l1",
        f_scale=4.0,
        max_nfev=3000,
    )
    errors = residual(result.x)
    return {
        "ref_rssi": float(result.x[0]),
        "path_loss_n": float(result.x[1]),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "cells": len(cells),
    }


if __name__ == "__main__":
    from kismap_web import main

    main()
