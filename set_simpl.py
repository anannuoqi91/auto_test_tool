#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Dict, List, Optional, Union
import argparse
import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict, Tuple
import time
import requests
import yaml
import base64
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from datetime import datetime
import websockets
import asyncio
import os
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

CONF_FILE = Path(__file__).resolve().parent / "config" / "interface_simpl.yaml"

HEADER_ENCODE_GZIP = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'content-language': 'en_US',
    # 'Authorization': '',
    'Referer': 'http://{service_ip}',
    'Connection': 'close',
}

HEADER_COMMON = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'content-language': 'en_US',
    # 'Authorization': '', # Need to add token
    'Origin': 'http://{service_ip}',
    'Referer': 'http://{service_ip}',
    'Connection': 'close',
}

CHANNEL_CONFIG = {
    "cluster": {
        "id": 1,
        "busId": 1,
        "channelName": (
            "omnisense/track/01/dynamic_points&"
            "omnisense/track/01/static_points&"
            "omnisense/cluster/01/boxes"
        ),
    },
    "tracker": {
        "id": 1,
        "busId": 1,
        "channelName": (
            "omnisense/track/01/dynamic_points&"
            "omnisense/track/01/static_points&"
            "omnisense/track/01/boxes"
        ),
    },
    "event": {
        "id": 1,
        "busId": 1,
        "channelName": (
            "omnisense/track/01/dynamic_points&"
            "omnisense/track/01/static_points&"
            "omnisense/event/01/boxes"
        ),
    },
}


class CognitionApiError(Exception):
    pass


class CognitionClient:
    def __init__(self, ip: str, timeout: int = 10):
        self.ip = ip
        self.timeout = timeout
        self.base_url = f"http://{ip}/prod-api/v2/cognition"

    def sub_stream(
        self,
        lidar_id: int,
        zone_names: Optional[List[str]] = None,
        event_names: Optional[List[str]] = None,
        zone_events: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """
        订阅认知数据流

        三种订阅方式三选一：
        1. zone_names: 指定区域列表（所有事件）
        2. event_names: 指定事件类型列表（所有区域）
        3. zone_events: 指定区域和对应事件
        4. 如果三者都不传：默认返回该 lidar 下所有区域的所有事件

        Returns:
            websocket url(str)

        Raises:
            ValueError: 参数不合法
            CognitionApiError: 接口调用失败
        """
        self._validate_sub_stream_args(
            lidar_id=lidar_id,
            zone_names=zone_names,
            event_names=event_names,
            zone_events=zone_events,
        )

        url = f"{self.base_url}/subStream"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "lidarId": lidar_id,
        }

        if zone_names is not None:
            payload["zoneNames"] = zone_names
        elif event_names is not None:
            payload["eventNames"] = event_names
        elif zone_events is not None:
            payload["zoneEvents"] = zone_events

        resp = requests.post(
            url=url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )

        # 尝试解析 json
        try:
            data = resp.json()
        except Exception:
            raise CognitionApiError(
                f"subStream 响应不是合法 JSON, status={resp.status_code}, body={resp.text}"
            )

        if resp.status_code != 200:
            raise CognitionApiError(
                f"subStream 请求失败, http_status={resp.status_code}, response={data}"
            )

        code = data.get("code")
        msg = data.get("msg")
        ws_url = data.get("data")

        if code != 200:
            raise CognitionApiError(
                f"subStream 业务失败, code={code}, msg={msg}, response={data}"
            )

        if not ws_url:
            raise CognitionApiError(
                f"subStream 返回成功但 data 为空, response={data}"
            )

        return ws_url

    @staticmethod
    def _validate_sub_stream_args(
        lidar_id: int,
        zone_names: Optional[List[str]],
        event_names: Optional[List[str]],
        zone_events: Optional[Dict[str, List[str]]],
    ) -> None:
        if not isinstance(lidar_id, int):
            raise ValueError("lidar_id 必须是 int")

        selected = sum(
            x is not None
            for x in (zone_names, event_names, zone_events)
        )

        if selected > 1:
            raise ValueError(
                "zone_names / event_names / zone_events 只能三选一，不能同时传多个"
            )

        if zone_names is not None:
            if not isinstance(zone_names, list) or not all(isinstance(x, str) for x in zone_names):
                raise ValueError("zone_names 必须是 string list，例如 ['Z1', 'Z2']")

        if event_names is not None:
            if not isinstance(event_names, list) or not all(isinstance(x, str) for x in event_names):
                raise ValueError(
                    "event_names 必须是 string list，例如 ['StoppedVehicleEvent', 'CongestionEvent']"
                )

        if zone_events is not None:
            if not isinstance(zone_events, dict):
                raise ValueError(
                    "zone_events 必须是 dict，例如 {'Z1': ['StoppedVehicleEvent']}")

            for zone, events in zone_events.items():
                if not isinstance(zone, str):
                    raise ValueError("zone_events 的 key 必须是区域名字符串")
                if not isinstance(events, list) or not all(isinstance(x, str) for x in events):
                    raise ValueError(
                        f"zone_events['{zone}'] 必须是 string list"
                    )


def get_yaml_info(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_apollo_container_path(container_path: str) -> bool:
    normalized = container_path.rstrip("/")
    return normalized == "/apollo" or normalized.startswith("/apollo/")


def _parse_bind_entry(bind_entry: str):
    parts = bind_entry.split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid docker bind entry: {bind_entry}")
    host_path = parts[0]
    container_path = parts[1]
    return host_path, container_path


def find_apollo_bind_path(container_name: str) -> str:
    """
    Find the host path bound to /apollo or /apollo/* for a docker container.
    """
    try:
        inspect_output = subprocess.check_output(
            ["docker", "inspect", container_name],
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"docker inspect failed for container {container_name}: {exc}"
        ) from exc

    try:
        inspect_data = json.loads(inspect_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"docker inspect returned invalid JSON for container {container_name}"
        ) from exc

    if not inspect_data:
        raise RuntimeError(f"Container not found: {container_name}")

    container_info = inspect_data[0]
    bind_entries = container_info.get("HostConfig", {}).get("Binds") or []
    for bind_entry in bind_entries:
        host_path, container_path = _parse_bind_entry(bind_entry)
        if _is_apollo_container_path(container_path):
            return host_path

    for mount in container_info.get("Mounts", []):
        destination = mount.get("Destination", "")
        if _is_apollo_container_path(destination):
            source = mount.get("Source")
            if source:
                return source

    raise RuntimeError(
        f"No bind path mapped to /apollo found for container {container_name}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Request simpl_channel_config to update lidar channels.",
    )
    parser.add_argument(
        "--base_url",
        default="http://localhost",
        help="Simpl service base URL, e.g. http://localhost or http://127.0.0.1:80",
    )
    parser.add_argument(
        "--channel_type",
        choices=sorted(CHANNEL_CONFIG.keys()),
        default="cluster",
        help="Predefined channel config profile",
    )
    parser.add_argument(
        "--bus_id",
        type=int,
        default=None,
        help="Optional busId override",
    )
    parser.add_argument(
        "--config_id",
        type=int,
        default=None,
        help="Optional request payload id override",
    )
    parser.add_argument(
        "--request_conf",
        default=str(CONF_FILE),
        help="Path to interface_simpl.yaml",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Print request information without sending it",
    )
    return parser.parse_args()


def build_payload(
    payload_template: Dict[str, Any],
    channel_type: str,
    bus_id: Optional[int] = None,
    config_id: Optional[int] = None,
) -> Dict[str, Any]:
    if channel_type not in CHANNEL_CONFIG:
        supported = ", ".join(sorted(CHANNEL_CONFIG))
        raise ValueError(
            f"Unsupported channel_type: {channel_type}. Supported values: {supported}"
        )

    payload = copy.deepcopy(payload_template)
    payload.update(CHANNEL_CONFIG[channel_type])

    if bus_id is not None:
        payload["busId"] = bus_id
    if config_id is not None:
        payload["id"] = config_id

    return payload


def _get_public_key(service_ip, try_num=10) -> str:
    """
    Get authentication public key.
    :param is_update: If True, get access token directly.
    :return: Public key in str.
    """
    HTTP_GET_PUBLIC_KEY = "http://{ip}/core/public-key"
    public_key = None
    while public_key is None and try_num > 0:
        try_num -= 1
        headers = copy.deepcopy(HEADER_ENCODE_GZIP)
        headers["Referer"] = headers["Referer"].format(
            service_ip=service_ip)
        get_url = HTTP_GET_PUBLIC_KEY.format(ip=service_ip)
        response = requests.get(url=get_url, headers=headers)
        if response.status_code != 200:
            logger.error(
                f"Get public key failed! Response: {response.status_code}")
            time.sleep(1)
        else:
            tmp = response.json()
            if 'data' in tmp and 'publicKey' in tmp['data']:
                public_key = tmp['data']['publicKey']
            else:
                logger.error(
                    f"Get public key failed! Response: re.search failed! Response: {response.text}")
                time.sleep(1)
    return public_key


def _encrypt_str_pkcs1v15(passwd: bytes, public_key=None):
    """
        Encrypt password.
        :param passwd: Password.
        :param public_key: Public key.
        :return: Encrypted password.
        """
    public_key_gem = f"-----BEGIN PUBLIC KEY-----\n" \
        f"{public_key}\n" \
        f"-----END PUBLIC KEY-----\n"

    public_key = serialization.load_pem_public_key(
        public_key_gem.encode(),
        backend=default_backend()
    )

    cipher_text = public_key.encrypt(
        passwd,
        padding.PKCS1v15()
    )

    cipher_text_str = base64.b64encode(cipher_text).decode()

    return cipher_text_str


def _get_access_token(user_name, service_ip, encrypted_passwd):
    HTTP_LOGIN = "http://{ip}/core/login"
    login_url = HTTP_LOGIN.format(ip=service_ip)

    headers = copy.deepcopy(HEADER_ENCODE_GZIP)
    headers["Referer"] = headers["Referer"].format(service_ip=service_ip)
    headers["Origin"] = f"http://{service_ip}"
    headers["Content-Type"] = "application/json"

    login_data = {
        "username": user_name,
        "password": encrypted_passwd,
    }

    response = requests.post(login_url, headers=headers, json=login_data)
    if response.status_code != 200:
        raise RuntimeError(
            f"Get access token failed! Response: {response.status_code}")
    else:
        tmp = response.json()
        if 'data' in tmp and 'token' in tmp['data']:
            token = tmp['data']['token']
        else:
            raise RuntimeError(
                f"Failed to get access token from response. {tmp}")
    return token


def get_authentication(user_name: str, password: str, service_ip: str = "127.0.0.1") -> str:

    # Get user public key
    public_key = _get_public_key(service_ip)
    if public_key is None:
        raise RuntimeError("Failed to get public key for authentication.")
    # Encrypt password with padding PKCS#1v1.5
    encrypted_passwd = _encrypt_str_pkcs1v15(
        passwd=password.encode(),
        public_key=public_key
    )
    # Get user access token
    token = _get_access_token(
        user_name=user_name,
        service_ip=service_ip,
        encrypted_passwd=encrypted_passwd
    )
    return token


def _request_deal(headers, url, type_, **kwargs):
    response = ''
    if type_ == 'get':
        response = requests.get(url=url, headers=headers, **kwargs)
    elif type_ == 'post':
        response = requests.post(url=url, headers=headers, **kwargs)
    elif type_ == 'put':
        response = requests.put(
            url, headers=headers, params=kwargs['params'], json=kwargs['json'], timeout=kwargs.get("timeout", 10.0))
    elif type_ == 'delete':
        response = requests.delete(url=url, headers=headers, **kwargs)
    return response


def multi_response(headers, url, type_, **kwargs):
    user_name = kwargs['user_name']
    password = kwargs['password']
    service_ip = kwargs['service_ip']
    token = get_authentication(user_name, password, service_ip)
    headers["Authorization"] = token
    response = _request_deal(headers, url, type_, **kwargs)
    return response


def change_channel(
    channel_type: str,
    user_name: str,
    password: str,
    *,
    request_conf: str = str(CONF_FILE),
    timeout: float = 10.0,
    dry_run: bool = False,
    bus_id: Optional[int] = None,
    config_id: Optional[int] = None,
    service_ip: str = "127.0.0.1"
) -> Any:
    """
    Change simpl channel using one of the predefined CHANNEL_CONFIG entries.

    Supported channel_type values: cluster, tracker, event.
    """
    SUBERCRIBE_URL = "http://{service_ip}/prod-api/lidar/channelConfig"

    headers = copy.deepcopy(HEADER_ENCODE_GZIP)
    headers.update(
        {"Referer": headers["Referer"].format(service_ip=service_ip)},)
    if "Content-Type" in headers:
        headers.pop("Content-Type")
    conf = get_yaml_info(request_conf)
    request_info = copy.deepcopy(conf["simpl_channel_config"])
    payload_template = request_info.get("payload") or {}
    payload = build_payload(
        payload_template=payload_template,
        channel_type=channel_type,
        bus_id=bus_id,
        config_id=config_id,
    )

    request_url = SUBERCRIBE_URL.format(service_ip=service_ip)
    logger.info("Request: %s %s", request_info["model"], request_url)
    logger.info("Payload: %s", json.dumps(payload, ensure_ascii=False))

    if dry_run:
        logger.info("Dry-run mode enabled, request not sent")
        return {
            "request_url": request_url,
            "method": request_info["model"],
            "payload": payload,
        }

    response = multi_response(headers, request_url, "put",
                              user_name=user_name, password=password, service_ip=service_ip, json=payload, params=request_info)

    if response.status_code == 200:
        response_dict = json.loads(response.text)
        out = response_dict["code"]
        logger.info(f"Upload loop success! Response: {out}")
        return True
    else:
        logger.error(f"Upload loop failed! Response: {response.text}")
        return False


def sub_cognition(lidar_id: str, service_ip: str = "127.0.0.1"):
    sub_cognition = CognitionClient(ip=service_ip)
    ws_url = sub_cognition.sub_stream(lidar_id=lidar_id)
    return ws_url


async def sub_cognition_stream(ws_url, dir, stop_event=None, started_event=None):
    try:
        async with websockets.connect(ws_url) as ws:
            if started_event is not None:
                started_event.set()
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                data = json.loads(message)
                cur_time = datetime.now()
                out_name = int(cur_time.timestamp() * 1000)
                with open(os.path.join(dir, f"{out_name}.json"), "w") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        if started_event is not None:
            started_event.set()
        logger.error("sub_cognition_stream failed: %s", e)


def main() -> int:
    args = parse_args()
    change_channel(
        channel_type=args.channel_type,
        base_url=args.base_url,
        request_conf=args.request_conf,
        timeout=args.timeout,
        dry_run=args.dry_run,
        bus_id=args.bus_id,
        config_id=args.config_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
