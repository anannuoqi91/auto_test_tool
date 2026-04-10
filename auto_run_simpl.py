import argparse
import asyncio
import ast
import configparser
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set, List, Optional, Tuple
from play_single_lidar import *
from set_simpl import *

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

CONF_FILE = Path(__file__).resolve().parent / \
    "config" / "interface_fake_lidar.yaml"
SSR_SETTINGS_FILE = Path.home() / ".ssr" / "settings.conf"
SSR_WINDOW_NAME = os.environ.get("SSR_WINDOW_NAME", "SimpleScreenRecorder")
SSR_LAUNCH_WAIT_SECONDS = float(os.environ.get("SSR_LAUNCH_WAIT_SECONDS", "1"))
SSR_CONTINUE_COUNT = int(os.environ.get("SSR_CONTINUE_COUNT", "3"))
SSR_SAVE_TAB_COUNT = int(os.environ.get("SSR_SAVE_TAB_COUNT", "2"))
SSR_SEARCH_RETRY_COUNT = int(os.environ.get("SSR_SEARCH_RETRY_COUNT", "20"))
SSR_FILE_WAIT_SECONDS = float(os.environ.get("SSR_FILE_WAIT_SECONDS", "20"))
DEFAULT_SCREEN_RECORD_BACKEND = os.environ.get(
    "SCREEN_RECORD_BACKEND", "gnome-shortcut").strip().lower()
GNOME_MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_SCREENCAST_SHORTCUT_KEY = "screencast"
GNOME_MAX_SCREENCAST_LENGTH_KEY = "max-screencast-length"
GNOME_DEFAULT_SCREENCAST_SHORTCUT = "ctrl+shift+alt+r"
GNOME_SCREEN_RECORD_AUTO_UNLIMITED = os.environ.get(
    "GNOME_SCREEN_RECORD_AUTO_UNLIMITED", "1").strip().lower() not in {
    "0", "false", "no"
}
VIDEO_FILE_SUFFIXES = (".webm", ".mkv", ".mp4")
SCREEN_RECORD_TARGET_FORMAT = os.environ.get(
    "SCREEN_RECORD_TARGET_FORMAT", "webm").strip().lower()


@dataclass
class ScreenRecordingSession:
    backend: str
    process: Optional[subprocess.Popen] = None
    window_id: Optional[str] = None
    output_template: Optional[Path] = None
    known_files: Set[str] = field(default_factory=set)
    started_at: float = 0.0
    candidate_dirs: Tuple[Path, ...] = field(default_factory=tuple)
    gnome_shortcut: Optional[str] = None
    restore_max_length: Optional[int] = None


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=""
    )
    parser.add_argument("--sim_ip", default="172.16.96.216")
    parser.add_argument("--fake_lidar_ip", default="172.30.0.2")
    parser.add_argument("--lidar_ids", default="11,10,21,31")
    parser.add_argument("--api_port", default=12628)
    parser.add_argument("--udp_port", default=8011)
    parser.add_argument("--tcp_port", default=8010)
    parser.add_argument("--speed", default=10000)
    parser.add_argument("--rewind", default=0)
    parser.add_argument("--start_after", default=1)
    parser.add_argument("--retry_count", default=3)
    parser.add_argument("--retry_interval", default=1.0)
    parser.add_argument("--wait_padding_sec", default=10.0)
    parser.add_argument("--keywords", default="")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--request_conf", default=str(CONF_FILE))
    parser.add_argument('--items', default="tracker,cluster,event",)
    parser.add_argument('--out_dir', default="./",)
    parser.add_argument('--container_name', default="OmniVidi_VL")
    parser.add_argument(
        "--screen_record_backend",
        default=DEFAULT_SCREEN_RECORD_BACKEND,
        choices=("ssr", "gnome-shortcut"),
    )
    return parser.parse_args()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto play single lidar data for Korail datasets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python play_single_lidar.py - -sim_ip 172.16.210.98 - -lidar_ids 11
  python play_single_lidar.py - -sim_ip 172.16.210.98 - -lidar_ids 11, 10
  python play_single_lidar.py - -sim_ip 172.16.210.98 - -lidar_ids 10, 11, 21, 31
        """,
    )
    parser.add_argument("--sim_ip", required=True,
                        help="Simulation host IP, e.g. 172.16.210.98")
    parser.add_argument(
        "--fake_lidar_ip",
        default="172.30.0.2",
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
    parser.add_argument('--items', required=True,
                        help="Comma-separated lidar IDs to play, e.g. cluster or cluster,tracker,event. ",)
    parser.add_argument('--out_dir', required=True,
                        help="Output directory for cognition data.",)
    parser.add_argument(
        "--screen_record_backend",
        default=DEFAULT_SCREEN_RECORD_BACKEND,
        choices=("ssr", "gnome-shortcut"),
        help="Screen recording backend: ssr or gnome-shortcut",
    )
    return parser.parse_args()


def get_docker_cur_time(container_name: str):
    try:
        result = subprocess.check_output(
            ["docker", "exec", container_name, "date", "+%s%3N"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(
            f"failed to get current time from container {container_name}: {stderr}"
        ) from exc

    return int(result)


def get_all_files(args, lidar_ids, keywords):
    conf = get_yaml_info(args.request_conf)
    fake_client = FakeLidarClient(args.fake_lidar_ip, conf, port=args.api_port)
    # 1. get all inno_pc files
    all_files = with_retry(
        "get_all_files",
        fake_client.get_all_files,
        retries=args.retry_count,
        interval_sec=args.retry_interval,
    )
    total_files = len(all_files)
    logger.info(f"Total files in fake lidar: {total_files}")
    if total_files == 0:
        logger.error(f"No files found for lidar IDs: {lidar_ids}")
        return 2
    # 2. split file to each group
    grouped = discover_files_by_lidar_id(
        all_files, lidar_ids=lidar_ids, keywords=keywords, verbose=args.verbose
    )

    # 3. log discovered files
    for lid in lidar_ids:
        files = grouped[lid]
        logger.info(f"LIDAR_{lid}: {len(files)} files discovered")
        if args.verbose:
            for f in files:
                logger.info(f"  {f}")
    return grouped, fake_client


def _run_cognition_stream(ws_url: str, output_dir: str, stop_event, started_event) -> None:
    asyncio.run(
        sub_cognition_stream(
            ws_url=ws_url,
            dir=output_dir,
            stop_event=stop_event,
            started_event=started_event,
        )
    )


def start_cognition_stream_worker(ws_url: str, output_dir: str, ready_timeout: float = 5.0):
    stop_event = threading.Event()
    started_event = threading.Event()
    stream_thread = threading.Thread(
        target=_run_cognition_stream,
        args=(ws_url, output_dir, stop_event, started_event),
        daemon=True,
    )
    stream_thread.start()

    if not started_event.wait(timeout=ready_timeout):
        logger.warning(
            "Cognition stream did not confirm startup within %.1fs", ready_timeout)

    return stop_event, stream_thread


def stop_cognition_stream_worker(stop_event, stream_thread, join_timeout: float = 5.0) -> None:
    stop_event.set()
    stream_thread.join(timeout=join_timeout)
    if stream_thread.is_alive():
        logger.warning(
            "Cognition stream thread did not exit within %.1fs", join_timeout)


def _missing_screen_recording_tools() -> List[str]:
    return [
        tool for tool in ("simplescreenrecorder", "xdotool")
        if shutil.which(tool) is None
    ]


def _sudo_prefix() -> List[str]:
    if os.geteuid() == 0:
        return []
    if shutil.which("sudo") is not None:
        return ["sudo"]
    raise RuntimeError(
        "SimpleScreenRecorder 未安装，且当前用户不是 root，也没有 sudo，无法自动安装。"
    )


def ensure_screen_recording_tools() -> None:
    missing_tools = _missing_screen_recording_tools()
    if not missing_tools:
        return

    logger.info(
        "Missing screen recording tools: %s. Installing now...",
        ", ".join(missing_tools),
    )
    sudo_prefix = _sudo_prefix()

    try:
        if shutil.which("apt-get") is not None:
            subprocess.check_call(sudo_prefix + ["apt-get", "update"])
            subprocess.check_call(
                sudo_prefix + ["apt-get", "install", "-y",
                               "simplescreenrecorder", "xdotool"]
            )
        elif shutil.which("dnf") is not None:
            subprocess.check_call(
                sudo_prefix + ["dnf", "install", "-y",
                               "simplescreenrecorder", "xdotool"]
            )
        elif shutil.which("yum") is not None:
            subprocess.check_call(
                sudo_prefix + ["yum", "install", "-y",
                               "simplescreenrecorder", "xdotool"]
            )
        elif shutil.which("pacman") is not None:
            subprocess.check_call(
                sudo_prefix + ["pacman", "-Sy", "--noconfirm",
                               "simplescreenrecorder", "xdotool"]
            )
        elif shutil.which("zypper") is not None:
            subprocess.check_call(
                sudo_prefix + ["zypper", "--non-interactive",
                               "install", "simplescreenrecorder", "xdotool"]
            )
        else:
            raise RuntimeError("未识别到支持的包管理器，无法自动安装 SimpleScreenRecorder。")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("安装 SimpleScreenRecorder 失败。") from exc

    missing_tools = _missing_screen_recording_tools()
    if missing_tools:
        raise RuntimeError(
            f"安装完成后仍缺少录屏依赖: {', '.join(missing_tools)}"
        )


def load_ssr_settings(settings_file: Path = SSR_SETTINGS_FILE) -> configparser.ConfigParser:
    if not settings_file.is_file():
        raise RuntimeError(
            f"未找到 SSR 配置文件: {settings_file}，请先手动打开一次 SimpleScreenRecorder 并配置输出文件。"
        )

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(
            settings_file.read_text(
                encoding="utf-8",
                errors="surrogateescape",
            )
        )
    except (OSError, configparser.Error) as exc:
        raise RuntimeError(f"读取 SSR 配置失败: {settings_file}") from exc
    return parser


def get_ssr_output_template(settings_file: Path = SSR_SETTINGS_FILE) -> Path:
    parser = load_ssr_settings(settings_file)
    output_file = parser.get("output", "file", fallback="").strip()
    if not output_file:
        raise RuntimeError(
            f"SSR 配置文件 {settings_file} 中未配置 output.file，无法定位录屏输出。"
        )
    return Path(output_file).expanduser()


def _normalize_screen_record_backend(backend: str) -> str:
    normalized = backend.strip().lower()
    if normalized not in {"ssr", "gnome-shortcut"}:
        raise RuntimeError(f"Unsupported screen recording backend: {backend}")
    return normalized


def _gsettings_get(schema: str, key: str):
    if shutil.which("gsettings") is None:
        return None

    result = subprocess.run(
        ["gsettings", "get", schema, key],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _gsettings_set(schema: str, key: str, value: str) -> None:
    result = subprocess.run(
        ["gsettings", "set", schema, key, value],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(
            f"gsettings set {schema} {key} {value} failed: {stderr}"
        )


def _parse_gnome_shortcut(binding: str) -> str | None:
    tokens = re.findall(r"<([^>]+)>", binding)
    key = re.sub(r"(?:<[^>]+>)", "", binding).strip()
    if not key:
        return None

    normalized_tokens = []
    for token in tokens:
        lowered = token.strip().lower()
        if lowered in {"ctrl", "control", "primary"}:
            normalized_tokens.append("ctrl")
        elif lowered in {"alt"}:
            normalized_tokens.append("alt")
        elif lowered in {"shift"}:
            normalized_tokens.append("shift")
        elif lowered in {"super", "meta"}:
            normalized_tokens.append("super")
        else:
            normalized_tokens.append(lowered)

    normalized_tokens.append(key.lower())
    return "+".join(normalized_tokens)


def _get_gnome_screencast_shortcut() -> str:
    override = os.environ.get("GNOME_SCREEN_RECORD_TOGGLE_KEY", "").strip()
    if override:
        return override

    raw_binding = _gsettings_get(
        GNOME_MEDIA_KEYS_SCHEMA, GNOME_SCREENCAST_SHORTCUT_KEY)
    if not raw_binding:
        return GNOME_DEFAULT_SCREENCAST_SHORTCUT
    if raw_binding in {"[]", "@as []"}:
        raise RuntimeError(
            "GNOME screencast shortcut is disabled. "
            "Enable it in Settings or set GNOME_SCREEN_RECORD_TOGGLE_KEY."
        )

    try:
        bindings = ast.literal_eval(raw_binding)
    except (SyntaxError, ValueError):
        bindings = []

    if isinstance(bindings, list):
        for binding in bindings:
            if not isinstance(binding, str):
                continue
            parsed = _parse_gnome_shortcut(binding)
            if parsed:
                return parsed

    return GNOME_DEFAULT_SCREENCAST_SHORTCUT


def _get_gnome_max_screencast_length() -> int | None:
    raw_value = _gsettings_get(
        GNOME_MEDIA_KEYS_SCHEMA, GNOME_MAX_SCREENCAST_LENGTH_KEY)
    if not raw_value:
        return None

    match = re.search(r"(\d+)$", raw_value)
    if not match:
        return None
    return int(match.group(1))


def _set_gnome_max_screencast_length(value: int) -> None:
    _gsettings_set(
        GNOME_MEDIA_KEYS_SCHEMA,
        GNOME_MAX_SCREENCAST_LENGTH_KEY,
        str(value),
    )


def _get_xdg_videos_dir() -> Path:
    if shutil.which("xdg-user-dir") is not None:
        try:
            output = subprocess.check_output(
                ["xdg-user-dir", "VIDEOS"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            output = ""
        if output:
            return Path(output).expanduser()

    fallback_candidates = (
        Path.home() / "Videos",
        Path.home() / "视频",
    )
    for candidate in fallback_candidates:
        if candidate.exists():
            return candidate
    return Path.home() / "Videos"


def _get_gnome_recording_candidate_dirs() -> Tuple[Path, ...]:
    seen: set[str] = set()
    candidates: List[Path] = []
    base_dirs = [
        _get_xdg_videos_dir(),
        Path.home() / "Videos",
        Path.home() / "视频",
    ]
    for base_dir in base_dirs:
        for candidate in (base_dir, base_dir / "Screencasts"):
            candidate_key = str(candidate)
            if candidate_key in seen:
                continue
            seen.add(candidate_key)
            candidates.append(candidate)
    return tuple(candidates)


def _list_recording_candidates_in_dirs(
    candidate_dirs: tuple[Path, ...],
) -> list[Path]:
    files_by_path: dict[str, Path] = {}
    for candidate_dir in candidate_dirs:
        if not candidate_dir.exists() or not candidate_dir.is_dir():
            continue
        for suffix in VIDEO_FILE_SUFFIXES:
            for path in candidate_dir.glob(f"*{suffix}"):
                if path.is_file():
                    files_by_path[str(path)] = path
    return sorted(
        files_by_path.values(),
        key=lambda path: path.stat().st_mtime,
    )


def ensure_screen_recording_ready(backend: str) -> None:
    if not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "当前环境未设置 DISPLAY，录屏功能需要在 X11 图形桌面会话中运行。"
        )

    backend = _normalize_screen_record_backend(backend)
    logger.info("Screen recording backend: %s", backend)

    if backend == "ssr":
        ensure_screen_recording_tools()
        output_template = get_ssr_output_template()
        logger.info("Screen recording output template: %s", output_template)
        return

    if shutil.which("xdotool") is None:
        raise RuntimeError(
            "gnome-shortcut backend requires xdotool, but it was not found."
        )

    shortcut = _get_gnome_screencast_shortcut()
    candidate_dirs = _get_gnome_recording_candidate_dirs()
    logger.info("GNOME screencast shortcut: %s", shortcut)
    logger.info(
        "GNOME screencast candidate dirs: %s",
        ", ".join(str(path) for path in candidate_dirs),
    )
    max_length = _get_gnome_max_screencast_length()
    if max_length is None:
        logger.warning(
            "Could not read GNOME max screencast length. Long recordings may be truncated."
        )
    elif max_length == 0:
        logger.info("GNOME max screencast length: unlimited")
    elif GNOME_SCREEN_RECORD_AUTO_UNLIMITED:
        logger.info(
            "GNOME max screencast length is %ss; it will be temporarily set to unlimited during recording.",
            max_length,
        )
    else:
        logger.warning(
            "GNOME max screencast length is %ss. Recordings longer than this may be truncated.",
            max_length,
        )


def _list_recording_candidates(output_template: Path):
    output_dir = output_template.parent
    if not output_dir.exists():
        return []

    if output_template.suffix:
        pattern = f"{output_template.stem}*{output_template.suffix}"
    else:
        pattern = f"{output_template.name}*"

    return sorted(
        (path for path in output_dir.glob(pattern) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )


def _find_ssr_window_id():
    try:
        output = subprocess.check_output(
            ["xdotool", "search", "--onlyvisible", "--name", SSR_WINDOW_NAME],
            text=True,
        )
    except subprocess.CalledProcessError:
        return None

    window_ids = [line.strip() for line in output.splitlines() if line.strip()]
    if not window_ids:
        return None
    return window_ids[0]


def _wait_for_ssr_window_id() -> str:
    for _ in range(SSR_SEARCH_RETRY_COUNT):
        window_id = _find_ssr_window_id()
        if window_id:
            return window_id
        time.sleep(0.5)
    raise RuntimeError("没有找到 SimpleScreenRecorder 窗口，请确认当前桌面会话可见。")


def _run_xdotool(args: List[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["xdotool", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(
            f"xdotool {' '.join(args)} failed with exit code {result.returncode}: {stderr}"
        )
    return result


def _activate_ssr_window(window_id: str) -> None:
    activate_result = _run_xdotool(
        ["windowactivate", "--sync", window_id],
        check=False,
    )
    if activate_result.returncode == 0:
        time.sleep(0.3)
        return

    logger.warning(
        "xdotool windowactivate failed for window %s: %s",
        window_id,
        (activate_result.stderr or "").strip(),
    )

    # Some window managers don't expose _NET_WM_DESKTOP, which makes
    # windowactivate fail even though the window is still controllable.
    _run_xdotool(["windowmap", window_id], check=False)
    _run_xdotool(["windowraise", window_id], check=False)
    focus_result = _run_xdotool(
        ["windowfocus", "--sync", window_id],
        check=False,
    )
    if focus_result.returncode != 0:
        logger.warning(
            "xdotool windowfocus also failed for window %s: %s. Continuing anyway.",
            window_id,
            (focus_result.stderr or "").strip(),
        )
    time.sleep(0.3)


def _send_ssr_key(window_id: str, key: str) -> None:
    _run_xdotool(["key", "--window", window_id, key])


def _is_ssr_running() -> bool:
    if shutil.which("pgrep") is None:
        return False
    result = subprocess.run(
        ["pgrep", "-x", "simplescreenrecorder"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _toggle_gnome_screen_recording(shortcut: str) -> None:
    _run_xdotool(["key", "--clearmodifiers", shortcut])


def start_screen_recording(backend: str) -> ScreenRecordingSession:
    backend = _normalize_screen_record_backend(backend)
    ensure_screen_recording_ready(backend)

    if backend == "gnome-shortcut":
        shortcut = _get_gnome_screencast_shortcut()
        candidate_dirs = _get_gnome_recording_candidate_dirs()
        known_files = {
            str(path) for path in _list_recording_candidates_in_dirs(candidate_dirs)
        }
        restore_max_length = None
        max_length = _get_gnome_max_screencast_length()
        if (
            GNOME_SCREEN_RECORD_AUTO_UNLIMITED
            and max_length is not None
            and max_length > 0
        ):
            try:
                _set_gnome_max_screencast_length(0)
            except RuntimeError as exc:
                logger.warning("%s", exc)
                logger.warning(
                    "GNOME max screencast length remains %ss. Long recordings may be truncated.",
                    max_length,
                )
            else:
                restore_max_length = max_length
                logger.info(
                    "Temporarily set GNOME max screencast length to unlimited (was %ss).",
                    max_length,
                )

        started_at = time.time()
        try:
            _toggle_gnome_screen_recording(shortcut)
            time.sleep(1.0)
        except Exception:
            if restore_max_length is not None:
                try:
                    _set_gnome_max_screencast_length(restore_max_length)
                except RuntimeError as exc:
                    logger.warning("%s", exc)
            raise
        logger.info("Screen recording started.")
        return ScreenRecordingSession(
            backend=backend,
            known_files=known_files,
            started_at=started_at,
            candidate_dirs=candidate_dirs,
            gnome_shortcut=shortcut,
            restore_max_length=restore_max_length,
        )

    output_template = get_ssr_output_template()
    if _is_ssr_running():
        raise RuntimeError(
            "检测到已有 SimpleScreenRecorder 进程在运行。请先关闭它，再执行自动录屏。"
        )

    known_files = {str(path)
                   for path in _list_recording_candidates(output_template)}
    process = subprocess.Popen(
        ["simplescreenrecorder"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(SSR_LAUNCH_WAIT_SECONDS)

    window_id = _wait_for_ssr_window_id()
    _activate_ssr_window(window_id)
    for _ in range(SSR_CONTINUE_COUNT):
        _send_ssr_key(window_id, "Return")
        time.sleep(0.5)

    _send_ssr_key(window_id, "Return")
    logger.info("Screen recording started.")
    return ScreenRecordingSession(
        backend=backend,
        process=process,
        window_id=window_id,
        output_template=output_template,
        known_files=known_files,
        started_at=time.time(),
    )


def _find_recent_recorded_file(
    known_files: set[str],
    started_at: float,
    list_candidates_fn,
) -> Path | None:
    deadline = time.time() + SSR_FILE_WAIT_SECONDS
    fallback_candidate: Path | None = None
    while time.time() < deadline:
        candidates = list_candidates_fn()
        new_candidates = [
            path for path in candidates if str(path) not in known_files
        ]
        if new_candidates:
            latest_new = new_candidates[-1]
            if latest_new.stat().st_mtime >= started_at - 1:
                return latest_new

        if candidates:
            latest_candidate = candidates[-1]
            if latest_candidate.stat().st_mtime >= started_at - 1:
                fallback_candidate = latest_candidate

        time.sleep(0.5)

    return fallback_candidate


def _find_recorded_file(session: ScreenRecordingSession) -> Path | None:
    if session.backend == "gnome-shortcut":
        return _find_recent_recorded_file(
            session.known_files,
            session.started_at,
            lambda: _list_recording_candidates_in_dirs(session.candidate_dirs),
        )

    if session.output_template is None:
        return None

    return _find_recent_recorded_file(
        session.known_files,
        session.started_at,
        lambda: _list_recording_candidates(session.output_template),
    )


def _close_screen_recording_app(session: ScreenRecordingSession) -> None:
    if session.process is None or session.window_id is None:
        return
    if session.process.poll() is not None:
        return

    _run_xdotool(["key", "--window", session.window_id, "alt+F4"], check=False)
    try:
        session.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning(
            "SimpleScreenRecorder did not exit within 5s after save.")


def stop_screen_recording(session: ScreenRecordingSession) -> Path | None:
    if session.backend == "gnome-shortcut":
        if not session.gnome_shortcut:
            raise RuntimeError(
                "GNOME recording session does not have a shortcut configured."
            )
        record_file = None
        try:
            _toggle_gnome_screen_recording(session.gnome_shortcut)
            time.sleep(1.0)
            record_file = _find_recorded_file(session)
        finally:
            if session.restore_max_length is not None:
                try:
                    _set_gnome_max_screencast_length(
                        session.restore_max_length)
                except RuntimeError as exc:
                    logger.warning("%s", exc)
                else:
                    logger.info(
                        "Restored GNOME max screencast length to %ss.",
                        session.restore_max_length,
                    )
        if record_file is None:
            logger.warning(
                "Screen recording finished, but no output file was detected.")
        else:
            logger.info("Screen recording saved to %s", record_file)
        return record_file

    if session.window_id is None:
        raise RuntimeError("SSR recording session does not have a window ID.")
    _activate_ssr_window(session.window_id)
    for _ in range(SSR_SAVE_TAB_COUNT):
        _send_ssr_key(session.window_id, "Tab")
        time.sleep(0.2)

    _send_ssr_key(session.window_id, "Return")
    record_file = _find_recorded_file(session)
    _close_screen_recording_app(session)

    if record_file is None:
        logger.warning(
            "Screen recording finished, but no output file was detected.")
    else:
        logger.info("Screen recording saved to %s", record_file)
    return record_file


def copy_recording_to_dir(record_file, target_dir):
    if record_file is None:
        return None
    if not record_file.is_file():
        logger.warning("Recorded file not found: %s", record_file)
        return None

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_format = SCREEN_RECORD_TARGET_FORMAT
    if target_format != "mp4":
        target_path = target_dir / record_file.name
        shutil.copy2(record_file, target_path)
        logger.info("Copied recorded file to %s", target_path)
        return target_path

    target_path = target_dir / f"{record_file.stem}.mp4"
    if record_file.suffix.lower() == ".mp4":
        shutil.copy2(record_file, target_path)
        logger.info("Copied recorded file to %s", target_path)
        return target_path

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        fallback_path = target_dir / record_file.name
        shutil.copy2(record_file, fallback_path)
        logger.warning(
            "ffmpeg not found, kept original recording format: %s",
            fallback_path,
        )
        return fallback_path

    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        str(record_file),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(target_path),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fallback_path = target_dir / record_file.name
        shutil.copy2(record_file, fallback_path)
        logger.warning(
            "ffmpeg convert to mp4 failed, kept original recording format: %s; error: %s",
            fallback_path,
            (result.stderr or "").strip(),
        )
        return fallback_path

    logger.info("Converted recorded file to %s", target_path)
    return target_path


def run_all() -> int:
    # args = _build_args()
    args = parse_args()
    lidar_ids = [x.strip() for x in args.lidar_ids.split(",") if x.strip()]
    keywords = [x.strip() for x in args.keywords.split(",") if x.strip()]
    simpl_channel = [x.strip() for x in args.items.split(",") if x.strip()]

    if not lidar_ids:
        logger.error("--lidar_ids must contain at least one lidar ID")
        return 1
    if not os.path.isfile(args.request_conf):
        logger.error(f"request conf not found: {args.request_conf}")
        return 1

    grouped, fake_client = get_all_files(args, lidar_ids, keywords)

    if args.dry_run:
        logger.info("Dry-run mode enabled, no playback started")
        return 0
    # subscribe to cognition stream
    ws_url = sub_cognition(lidar_id=1)
    if ws_url.startswith("ws"):
        logger.info(f"Subscribed to cognition stream: {ws_url}")
    else:
        logger.error(f"Failed to subscribe to cognition stream: {ws_url}")
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    # check record tool
    ensure_screen_recording_ready(args.screen_record_backend)

    apollo_host_path = find_apollo_bind_path(args.container_name)
    print(apollo_host_path)
    for c_n in simpl_channel:
        # set channel
        if change_channel(channel_type=c_n, user_name="operator", password="operator"):
            logger.info(f"set channel to {c_n}")
        else:
            logger.error(f"set channel to {c_n} failed")
            continue
        played_count = 0
        for lid in lidar_ids:
            files = grouped[lid]
            if not files:
                logger.warning(f"No files for LIDAR_{lid}, skipping")
                continue
            logger.info(
                f"===== Start playing LIDAR_{lid} ({len(files)} files) =====")
            for file_idx, file_path in enumerate(files, start=1):
                # 1. mkdir name if not exist
                file_name = os.path.basename(file_path)
                dir_name = os.path.join(args.out_dir, file_name, c_n)
                if os.path.exists(dir_name):
                    shutil.rmtree(dir_name)
                os.makedirs(dir_name, exist_ok=True)
                # start record
                record_session = start_screen_recording(
                    args.screen_record_backend)
                record_file = None

                # 2. start cognition stream first, then play the lidar file.
                cognition_stream_dir = os.path.join(
                    str(dir_name), "cognition_stream")
                os.makedirs(cognition_stream_dir, exist_ok=True)
                play_error = None
                stop_event = None
                stream_thread = None
                start_time = None
                try:
                    stop_event, stream_thread = start_cognition_stream_worker(
                        ws_url=ws_url,
                        output_dir=cognition_stream_dir,
                    )
                    start_time = get_docker_cur_time(args.container_name)
                    play_single_file(
                        fake_client=fake_client,
                        args=args,
                        lidar_id=lid,
                        file_path=file_path,
                        file_idx=file_idx,
                        total_files=len(files),
                    )
                except Exception as exc:
                    play_error = exc
                finally:
                    if stop_event is not None and stream_thread is not None:
                        stop_cognition_stream_worker(stop_event, stream_thread)
                end_time = get_docker_cur_time(args.container_name)
                # end record
                record_file = stop_screen_recording(record_session)

                # save time range to json file
                with open(os.path.join(dir_name, f"{file_name}.json"), "w") as f:
                    json.dump(
                        {"start_time": start_time, "end_time": end_time},
                        f,
                        ensure_ascii=False,
                        indent=4,
                    )
                # cp record file to dir_name
                copy_recording_to_dir(record_file, dir_name)
                if play_error is not None:
                    raise play_error

                played_count += 1
            logger.info(f"===== Finished LIDAR_{lid} =====")

    # copy log to out_dir
    log_dir = Path(apollo_host_path) / "data" / "log"
    out_dir = Path(args.out_dir)
    target_dir = out_dir / log_dir.name
    if target_dir.exists():
        shutil.rmtree(target_dir)
    # copy log dir to out_dir
    shutil.copytree(log_dir, target_dir, dirs_exist_ok=True)
    return 0


if __name__ == "__main__":
    run_all()
