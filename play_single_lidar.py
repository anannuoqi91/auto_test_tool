#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Auto play single lidar data for Korail datasets.

File naming convention:
    LIDAR_10_<timestamp>.inno_pc
    LIDAR_11_<timestamp>.inno_pc
    LIDAR_21_<timestamp>.inno_pc
    LIDAR_31_<timestamp>.inno_pc

Usage examples:
    # Play all LIDAR_11 files
    python play_single_lidar.py --sim_ip 172.16.210.98 --lidar_ids 11

    # Play all LIDAR_11 files first, then all LIDAR_10 files
    python play_single_lidar.py --sim_ip 172.16.210.98 --lidar_ids 11,10

    # Play all four lidar IDs in order
    python play_single_lidar.py --sim_ip 172.16.210.98 --lidar_ids 10,11,21,31
"""

import argparse
import copy
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import logging

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)





def get_yaml_info(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class FakeLidarClient:
    def __init__(self, host_ip: str, conf: dict, port: int = 12628, timeout: float = 10.0) -> None:
        self.host_ip = host_ip
        self.conf = conf
        self.port = port
        self.url = f"http://{host_ip}:{port}"
        self.timeout = timeout

    def _send_request(self, request_info: dict, json_body=None):
        ext_url = request_info["ext_url"]
        request_url = f"{self.url}{ext_url}"
        model = request_info["model"]
        parameters = request_info.get("parameters")

        if model == "GET":
            response = requests.get(
                request_url, params=parameters, timeout=self.timeout)
        elif model == "POST":
            response = requests.post(
                request_url, params=parameters, json=json_body, timeout=self.timeout)
        else:
            raise RuntimeError(f"Unsupported request model: {model}")

        if response.status_code != 200:
            raise RuntimeError(
                f"HTTP {response.status_code} at {request_url}: {response.text[:200]}")
        return response.json()

    def get_all_files(self) -> List[str]:
        response = self._send_request(self.conf["fakelidar_get_files"])
        return response.get("files", [])

    def get_duration(self, inno_pc_path: str) -> int:
        req = copy.deepcopy(self.conf["fakelidar_getinfo"])
        req["parameters"]["path"] = inno_pc_path
        response = self._send_request(req)
        return int(response["info"]["duration"])

    def single_stop(self) -> None:
        self._send_request(self.conf["fakelidar_single_stop"])

    def single_start(self, payload: dict) -> None:
        self._send_request(
            self.conf["fakelidar_single_start"], json_body=payload)


def with_retry(action_name: str, fn, retries: int, interval_sec: float):
    last_err = None
    for idx in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning(f"{action_name} failed ({idx}/{retries}): {exc}")
            if idx < retries:
                time.sleep(interval_sec)
    raise RuntimeError(
        f"{action_name} failed after {retries} retries: {last_err}")


def extract_lidar_id(path: str) -> str:
    """
    Extract lidar ID from filename.
    e.g. LIDAR_11_1775202447313.inno_pc -> '11'
         LIDAR_10_1775202447314.inno_pc -> '10'
    """
    file_name = os.path.basename(path)
    match = re.match(r"LIDAR_(\d+)_", file_name, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def discover_files_by_lidar_id(
    file_paths: List[str],
    lidar_ids: List[str],
    keywords: Optional[List[str]] = None,
    verbose: bool = False,
) -> Dict[str, List[str]]:
    """
    Group files by lidar ID and return only those matching requested IDs.
    Returns dict: lidar_id -> sorted list of file paths.
    """
    keywords = keywords or []
    grouped: Dict[str, List[str]] = {lid: [] for lid in lidar_ids}

    for path in file_paths:
        if keywords and not any(k in path for k in keywords):
            continue
        lid = extract_lidar_id(path)
        if not lid:
            if verbose:
                logger.warning(f"Skip file (cannot parse lidar ID): {path}")
            continue
        if lid in grouped:
            grouped[lid].append(path)

    for lid in lidar_ids:
        grouped[lid] = sorted(grouped[lid])

    return grouped


def build_single_lidar_payload(
    file_path: str,
    fake_lidar_ip: str,
    sim_ip: str,
    udp_port: int,
    tcp_port: int,
    speed: int,
    start_after: int,
    duration: int,
    rewind: int = 0,
) -> dict:
    return {
        "lidar_ip": fake_lidar_ip,
        "file": file_path,
        "udp_ip": sim_ip,
        "udp_port": udp_port,
        "udp_port_message": udp_port + 1,
        "udp_port_status": udp_port + 2,
        "tcp_port": tcp_port,
        "rewind": rewind,
        "speed": speed,
        "start_after": start_after,
        "duration": duration,
    }


def play_single_file(
    fake_client: FakeLidarClient,
    args: argparse.Namespace,
    lidar_id: str,
    file_path: str,
    file_idx: int,
    total_files: int,
) -> None:
    logger.info(f"[LIDAR_{lidar_id}] file {file_idx}/{total_files}: {file_path}")

    duration = with_retry(
        f"get_duration({os.path.basename(file_path)})",
        lambda fp=file_path: fake_client.get_duration(fp),
        retries=args.retry_count,
        interval_sec=args.retry_interval,
    )

    payload = build_single_lidar_payload(
        file_path=file_path,
        fake_lidar_ip=args.fake_lidar_ip,
        sim_ip=args.sim_ip,
        udp_port=args.udp_port,
        tcp_port=args.tcp_port,
        speed=args.speed,
        start_after=args.start_after,
        duration=max(1, duration - 1),
        rewind=args.rewind,
    )

    with_retry(
        f"single_stop(LIDAR_{lidar_id})",
        fake_client.single_stop,
        retries=args.retry_count,
        interval_sec=args.retry_interval,
    )
    time.sleep(1.0)
    with_retry(
        f"single_start(LIDAR_{lidar_id})",
        lambda p=payload: fake_client.single_start(p),
        retries=args.retry_count,
        interval_sec=args.retry_interval,
    )

    wait_sec = payload["duration"] + args.wait_padding_sec
    logger.info(
        f"LIDAR_{lidar_id} playing {os.path.basename(file_path)}, wait {wait_sec:.1f}s")
    time.sleep(wait_sec)
    logger.info(f"[LIDAR_{lidar_id}] file {file_idx}/{total_files} done")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto play single lidar data for Korail datasets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python play_single_lidar.py --sim_ip 172.16.210.98 --lidar_ids 11
  python play_single_lidar.py --sim_ip 172.16.210.98 --lidar_ids 11,10
  python play_single_lidar.py --sim_ip 172.16.210.98 --lidar_ids 10,11,21,31
        """,
    )
    parser.add_argument("--sim_ip", required=True,
                        help="Simulation host IP, e.g. 172.16.210.98")
    parser.add_argument(
        "--fake_lidar_ip",
        default="172.30.0.3",
        help="Fake lidar IP for single lidar replay",
    )
    parser.add_argument(
        "--lidar_ids",
        required=True,
        help="Comma-separated lidar IDs to play, e.g. 11 or 11,10,21,31. "
        "Files are played in the order of IDs specified.",
    )
    parser.add_argument("--api_port", type=int,
                        default=12628, help="FakeLidar API port")
    parser.add_argument("--udp_port", type=int, default=8011,
                        help="UDP port for replay stream")
    parser.add_argument("--tcp_port", type=int, default=8010,
                        help="TCP port for replay stream")
    parser.add_argument("--speed", type=int,
                        default=10000, help="Replay speed")
    parser.add_argument("--rewind", type=int, default=0,
                        help="Rewind value (0 = play once)")
    parser.add_argument("--start_after", type=int, default=1,
                        help="Start after delay (seconds)")
    parser.add_argument("--retry_count", type=int, default=3,
                        help="Retry count for HTTP operations")
    parser.add_argument("--retry_interval", type=float,
                        default=1.0, help="Retry interval in seconds")
    parser.add_argument("--wait_padding_sec", type=float,
                        default=10.0, help="Wait seconds after each play")
    parser.add_argument(
        "--keywords",
        default="",
        help="Optional comma-separated keywords for file filtering, e.g. korail,rain",
    )
    parser.add_argument("--verbose", action="store_true",
                        help="Print extra discovery diagnostics")
    parser.add_argument("--dry_run", action="store_true",
                        help="Only print discovered files without playing")
    parser.add_argument(
        "--request_conf",
        default=str(Path(__file__).resolve().parent /
                    "config" / "interface_fake_lidar.yaml"),
        help="Path to interface_fake_lidar.yaml",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lidar_ids = [x.strip() for x in args.lidar_ids.split(",") if x.strip()]
    keywords = [x.strip() for x in args.keywords.split(",") if x.strip()]

    if not lidar_ids:
        logger.error("--lidar_ids must contain at least one lidar ID")
        return 1
    if not os.path.isfile(args.request_conf):
        logger.error(f"request conf not found: {args.request_conf}")
        return 1

    conf = get_yaml_info(args.request_conf)
    fake_client = FakeLidarClient(args.fake_lidar_ip, conf, port=args.api_port)

    all_files = with_retry(
        "get_all_files",
        fake_client.get_all_files,
        retries=args.retry_count,
        interval_sec=args.retry_interval,
    )

    grouped = discover_files_by_lidar_id(
        all_files, lidar_ids=lidar_ids, keywords=keywords, verbose=args.verbose
    )

    total_files = sum(len(files) for files in grouped.values())
    if total_files == 0:
        logger.error(f"No files found for lidar IDs: {lidar_ids}")
        return 2

    for lid in lidar_ids:
        files = grouped[lid]
        logger.info(f"LIDAR_{lid}: {len(files)} files discovered")
        if args.verbose:
            for f in files:
                logger.info(f"  {f}")

    if args.dry_run:
        logger.info("Dry-run mode enabled, no playback started")
        return 0

    played_count = 0
    for lid in lidar_ids:
        files = grouped[lid]
        if not files:
            logger.warning(f"No files for LIDAR_{lid}, skipping")
            continue

        logger.info(
            f"===== Start playing LIDAR_{lid} ({len(files)} files) =====")
        for file_idx, file_path in enumerate(files, start=1):
            play_single_file(
                fake_client=fake_client,
                args=args,
                lidar_id=lid,
                file_path=file_path,
                file_idx=file_idx,
                total_files=len(files),
            )
            played_count += 1

        logger.info(f"===== Finished LIDAR_{lid} =====")

    logger.info(f"All playback completed. Total files played: {played_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
