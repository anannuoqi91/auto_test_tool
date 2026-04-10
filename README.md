# auto_run_simpl.py 使用说明

`auto_run_simpl.py` 用于把 Korail 的 `.inno_pc` 数据按指定雷达顺序自动回放，并在每次回放期间同时完成以下动作：

- 切换 SIMPL channel
- 订阅 cognition websocket 并持续落盘 JSON
- 启动桌面录屏
- 记录容器内起止时间戳
- 复制 `/apollo/data/log` 到输出目录

当前脚本入口是 [auto_run_simpl.py](/home/demo/Documents/code/auto_play_korail_data/auto_run_simpl.py)。

## 功能概览

- 支持按 `lidar_id` 顺序批量回放 `.inno_pc`
- 支持 `cluster`、`tracker`、`event` 三种 channel，支持一次跑多个
- 回放期间自动保存 cognition stream 原始 JSON
- 默认使用 Ubuntu/GNOME 系统录屏快捷键录制桌面
- 录屏文件默认转成 `.mp4`
- 为每条回放保存容器内 `start_time` / `end_time`
- 回放结束后复制 Apollo 日志目录

## 依赖和前置条件

### Python 依赖

```bash
pip install requests pyyaml cryptography websockets
```

### 系统依赖

- `docker`
- `xdotool`
- `ffmpeg`
- X11 图形桌面环境

如果你要使用 `ssr` 录屏后端，还需要：

- `simplescreenrecorder`
- `~/.ssr/settings.conf` 已存在，并且在 SSR 里手动配置过输出文件

### 运行前必须满足的服务条件

- FakeLidar API 可访问
- 本机 `127.0.0.1` 上的 SIMPL 服务可访问
- `operator / operator` 可以正常登录 SIMPL
- cognition 接口可以成功返回 websocket 地址
- `--container_name` 对应的 Docker 容器存在
- 该容器有 `/apollo` 挂载，且宿主机能访问 `/apollo/data/log`
- 已打开SIMPL前端页面并调整好角度，确保所有雷达都能被看到
- fakelidar已安装，启动

## 输入数据要求

脚本按文件名中的 lidar ID 进行分组，文件名需要满足：

```text
LIDAR_{id}_{timestamp}.inno_pc
```

例如：

- `LIDAR_10_1775202447314.inno_pc`
- `LIDAR_11_1775202447313.inno_pc`
- `LIDAR_21_1775202447316.inno_pc`
- `LIDAR_31_1775202447318.inno_pc`

## 最常用命令

### 基本运行

```bash
python3 auto_run_simpl.py \
  --sim_ip 172.16.210.98 \
  --lidar_ids 11,10 \
  --items tracker,cluster,event \
  --out_dir ./output
```

含义：

- 先回放所有 `LIDAR_11`
- 再回放所有 `LIDAR_10`
- 每个文件分别跑 `tracker`、`cluster`、`event`
- 输出保存到 `./output`

### 只跑单个 channel

```bash
python3 auto_run_simpl.py \
  --sim_ip 172.16.210.98 \
  --lidar_ids 11 \
  --items tracker \
  --out_dir ./output
```

### 使用关键字过滤文件

```bash
python3 auto_run_simpl.py \
  --sim_ip 172.16.210.98 \
  --lidar_ids 11,10 \
  --items tracker \
  --keywords korail,rain \
  --out_dir ./output
```

### 预览文件但不实际执行

```bash
python3 auto_run_simpl.py \
  --sim_ip 172.16.210.98 \
  --lidar_ids 11,10,21,31 \
  --items tracker \
  --out_dir ./output \
  --dry_run \
  --verbose
```

## 参数说明

| 参数 | 是否必填 | 默认值 | 说明 |
|---|---|---:|---|
| `--sim_ip` | 是 | 无 | 仿真主机 IP |
| `--fake_lidar_ip` | 否 | `172.30.0.3` | FakeLidar 服务 IP |
| `--lidar_ids` | 是 | 无 | 逗号分隔的雷达顺序，例如 `11,10,21,31` |
| `--api_port` | 否 | `12628` | FakeLidar API 端口 |
| `--udp_port` | 否 | `8011` | 回放 UDP 端口 |
| `--tcp_port` | 否 | `8010` | 回放 TCP 端口 |
| `--speed` | 否 | `10000` | 回放速度 |
| `--rewind` | 否 | `0` | 回放模式，`0` 表示播一次 |
| `--start_after` | 否 | `1` | 启动回放前延迟秒数 |
| `--retry_count` | 否 | `3` | HTTP 请求重试次数 |
| `--retry_interval` | 否 | `1.0` | HTTP 重试间隔，单位秒 |
| `--wait_padding_sec` | 否 | `10.0` | 单文件回放结束后额外等待秒数 |
| `--keywords` | 否 | 空 | 路径关键字过滤，多个值用逗号分隔 |
| `--verbose` | 否 | `false` | 打印更详细的发现日志 |
| `--dry_run` | 否 | `false` | 只发现文件，不启动回放 |
| `--request_conf` | 否 | `config/interface_fake_lidar.yaml` | FakeLidar 接口配置文件 |
| `--items` | 是 | 无 | channel 列表，例如 `tracker,cluster,event` |
| `--out_dir` | 是 | 无 | 输出目录 |
| `--screen_record_backend` | 否 | `gnome-shortcut` | 录屏后端，支持 `gnome-shortcut` 和 `ssr` |

### `--items` 可选值

- `tracker`
- `cluster`
- `event`

脚本会按你给的顺序依次切换 channel 并执行整轮回放。

## 录屏说明

### 默认后端：`gnome-shortcut`

默认使用 Ubuntu/GNOME 的系统录屏快捷键。

特点：

- 不依赖 SimpleScreenRecorder 窗口状态
- 会自动查找系统录屏输出目录
- 录屏结束后默认转成 `.mp4`
- 如果系统允许，会临时把 GNOME 的最大录屏时长改成 unlimited，结束后再恢复

### 可选后端：`ssr`

如果你仍要使用 SimpleScreenRecorder：

```bash
python3 auto_run_simpl.py \
  --sim_ip 172.16.210.98 \
  --lidar_ids 11 \
  --items tracker \
  --out_dir ./output \
  --screen_record_backend ssr
```

使用前请确认：

- `simplescreenrecorder` 已安装
- `~/.ssr/settings.conf` 存在
- 你已经手动打开过一次 SSR 并配置好输出文件

## 录屏输出格式

当前默认目标格式是 `mp4`。

处理逻辑：

- 如果录到的本身就是 `.mp4`，直接复制到输出目录
- 如果录到的是 `.webm` 或 `.mkv`，会自动用 `ffmpeg` 转成 `.mp4`
- 如果 `ffmpeg` 转换失败，会保留原始文件格式，并打 warning

## 输出目录结构

假设：

- `--out_dir ./output`
- 文件名为 `LIDAR_11_1775195599939.inno_pc`
- channel 为 `tracker`

则输出大致如下：

```text
output/
├── LIDAR_11_1775195599939.inno_pc/
│   └── tracker/
│       ├── cognition_stream/
│       │   ├── 1775702506625.json
│       │   ├── 1775702507731.json
│       │   └── ...
│       ├── LIDAR_11_1775195599939.inno_pc.json
│       └── *.mp4
└── log/
    └── ...
```

其中：

- `cognition_stream/*.json`
  订阅 websocket 后按接收时刻落盘的原始 cognition 数据
- `LIDAR_11_1775195599939.inno_pc.json`
  当前回放在容器内的开始和结束时间
- `*.mp4`
  录屏文件
- `log/`
  从容器 `/apollo/data/log` 复制出的日志目录

## 执行流程

每个 channel、每个文件都会按下面顺序执行：

1. 切换 SIMPL channel
2. 启动录屏
3. 启动 cognition stream 订阅线程
4. 获取容器内当前时间，记为 `start_time`
5. 调用 FakeLidar 回放当前 `.inno_pc`
6. 停止 cognition stream
7. 再次获取容器内当前时间，记为 `end_time`
8. 结束录屏并保存视频
9. 写入时间范围 JSON
10. 复制视频到对应输出目录

## 环境变量

脚本支持以下环境变量：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `SCREEN_RECORD_BACKEND` | `gnome-shortcut` | 默认录屏后端 |
| `SCREEN_RECORD_TARGET_FORMAT` | `mp4` | 录屏目标格式 |
| `GNOME_SCREEN_RECORD_TOGGLE_KEY` | 空 | 覆盖 GNOME 录屏快捷键，例如 `ctrl+shift+alt+r` |
| `GNOME_SCREEN_RECORD_AUTO_UNLIMITED` | `1` | 是否自动把 GNOME 录屏时长改为 unlimited |
| `SSR_WINDOW_NAME` | `SimpleScreenRecorder` | SSR 窗口标题匹配 |
| `SSR_LAUNCH_WAIT_SECONDS` | `1` | SSR 启动等待时间 |
| `SSR_CONTINUE_COUNT` | `3` | SSR 初始 Continue 次数 |
| `SSR_SAVE_TAB_COUNT` | `2` | SSR 保存阶段的 Tab 次数 |
| `SSR_SEARCH_RETRY_COUNT` | `20` | 查找 SSR 窗口重试次数 |
| `SSR_FILE_WAIT_SECONDS` | `20` | 等待录屏文件出现的超时时间 |

示例：

```bash
SCREEN_RECORD_BACKEND=gnome-shortcut \
SCREEN_RECORD_TARGET_FORMAT=mp4 \
python3 auto_run_simpl.py \
  --sim_ip 172.16.210.98 \
  --lidar_ids 11 \
  --items tracker \
  --out_dir ./output
```

## 常见问题

### 1. 提示 `当前环境未设置 DISPLAY`

原因：

- 当前不是图形桌面会话
- 通过纯 SSH 或无桌面环境运行

处理：

- 在本地图形桌面终端中运行
- 确认 `echo $DISPLAY` 非空

### 2. 录屏能启动，但没有生成视频

优先检查：

- 系统录屏快捷键是否被改掉
- 当前会话是否真的是 GNOME/Ubuntu 图形桌面
- `xdotool` 是否已安装
- 输出目录 `~/视频` 或 `~/Videos/Screencasts` 下是否实际生成了源文件

### 3. 视频不是 `.mp4`

脚本默认会转成 `.mp4`。如果最终还是原格式，通常说明：

- `ffmpeg` 不存在
- `ffmpeg` 转码失败

此时日志里会有 warning，并保留原始录屏文件。

### 4. 提示无法找到 `/apollo` 挂载

脚本会对 `--container_name` 执行 `docker inspect`，并查找 `/apollo` 或 `/apollo/*` 的挂载点。

请确认：

- 容器名称正确
- 容器已启动
- 容器里确实挂载了 `/apollo`

### 5. channel 切换失败

请检查：

- 本机 `127.0.0.1` 的 SIMPL 服务是否正常
- `operator / operator` 账号密码是否可用
- `config/interface_simpl.yaml` 中的接口配置是否正确

## 相关文件

- [auto_run_simpl.py](/home/demo/Documents/code/auto_play_korail_data/auto_run_simpl.py)
- [play_single_lidar.py](/home/demo/Documents/code/auto_play_korail_data/play_single_lidar.py)
- [set_simpl.py](/home/demo/Documents/code/auto_play_korail_data/set_simpl.py)
- [config/interface_fake_lidar.yaml](/home/demo/Documents/code/auto_play_korail_data/config/interface_fake_lidar.yaml)
- [config/interface_simpl.yaml](/home/demo/Documents/code/auto_play_korail_data/config/interface_simpl.yaml)
