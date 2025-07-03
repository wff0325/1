# -*- coding: utf-8 -*-
import os
import sys
import json
import random
import time
import shutil
import subprocess
from pathlib import Path
import urllib.request
import ssl
import tarfile
from datetime import datetime  # <--- 新增的导入语句
import streamlit as st

# ======== 核心：这是一个后台启动器，不需要任何UI ========

# 1. 基本配置和路径设置
st.set_page_config(page_title="Service Launcher", layout="wide") # 页面本身不会显示，但设置一下无妨

APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
LOG_FILE = INSTALL_DIR / "argo.log"

# 创建目录
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== 2. 辅助函数 ========

def print_and_log(message):
    """在终端和日志文件中同时打印消息"""
    print(message)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now()}] {message}\n")

def download_file(url, target_path):
    """下载文件，并在终端打印进度"""
    print_and_log(f"Downloading {Path(url).name}...")
    try:
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        print_and_log(f"Successfully downloaded to {target_path}")
        return True
    except Exception as e:
        print_and_log(f"ERROR: Failed to download {url}. Reason: {e}")
        return False

# ======== 3. 核心业务逻辑 ========

def run_services():
    """主函数：加载配置、下载依赖、启动服务"""
    
    # --- 加载配置 ---
    try:
        port_value = st.secrets.get("PORT") or random.randint(10000, 20000)
        config = {
            "DOMAIN": st.secrets["DOMAIN"],
            "CF_TOKEN": st.secrets["CF_TOKEN"],
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": int(port_value),
            "STATIC_PORT": int(port_value) + 1
        }
        print_and_log("Configuration loaded successfully.")
    except KeyError as e:
        print_and_log(f"FATAL ERROR: Missing secret: {e}. Deployment cannot continue.")
        st.error(f"错误: 缺少必要的 Secret 配置项: {e}。请在应用的 Secrets 中设置它。")
        return # 停止执行

    # --- 检查并下载 sing-box ---
    singbox_path = INSTALL_DIR / "sing-box"
    if not singbox_path.exists():
        arch = "amd64"
        sb_version = "1.9.0-beta.11"
        sb_name = f"sing-box-{sb_version}-linux-{arch}"
        sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"
        tar_path = INSTALL_DIR / "sing-box.tar.gz"
        if download_file(sb_url, tar_path):
            try:
                with tarfile.open(tar_path, "r:gz") as tar:
                    tar.extractall(path=INSTALL_DIR, filter='data')
                shutil.move(INSTALL_DIR / sb_name / "sing-box", singbox_path)
                shutil.rmtree(INSTALL_DIR / sb_name); tar_path.unlink()
                print_and_log("sing-box extracted successfully.")
            except Exception as e:
                print_and_log(f"FATAL ERROR: Failed to extract sing-box: {e}")
                return
    else:
        print_and_log("sing-box already exists.")

    # --- 检查并下载 cloudflared ---
    cloudflared_path = INSTALL_DIR / "cloudflared"
    if not cloudflared_path.exists():
        arch = "amd64"
        cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
        if not download_file(cf_url, cloudflared_path):
            print_and_log("FATAL ERROR: Failed to download cloudflared.")
            return
    else:
        print_and_log("cloudflared already exists.")
        
    # --- 启动伪装网站服务器 ---
    # 它会托管你仓库根目录下的 index.html
    decoy_html_path = APP_ROOT / "index.html"
    if not decoy_html_path.exists():
        print_and_log("WARNING: index.html not found in the repository root. Decoy website will not work.")
    
    server_cmd = [
        sys.executable, '-m', 'http.server',
        '--directory', str(APP_ROOT),
        '--bind', '127.0.0.1',
        str(config['STATIC_PORT'])
    ]
    with open(LOG_FILE, "a") as log_f:
        subprocess.Popen(server_cmd, stdout=log_f, stderr=log_f)
    print_and_log(f"Internal static server started on port {config['STATIC_PORT']}.")

    # --- 配置并启动 sing-box ---
    ws_path = f"/{config['UUID'][:8]}-vm"
    sb_config_dict = {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": config['PORT'],
                      "users": [{"uuid": config['UUID'], "alterId": 0}],
                      "transport": {"type": "ws", "path": ws_path},
                      "fallbacks": [{"dest": config['STATIC_PORT']}]
                     }],
        "outbounds": [{"type": "direct"}]
    }
    (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config_dict, indent=2))
    
    os.chmod(singbox_path, 0o755)
    singbox_cmd = [str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")]
    with open(LOG_FILE, "a") as log_f:
        subprocess.Popen(singbox_cmd, stdout=log_f, stderr=log_f)
    print_and_log(f"sing-box started, listening on port {config['PORT']}.")

    # --- 启动 cloudflared ---
    os.chmod(cloudflared_path, 0o755)
    cf_cmd = [
        str(cloudflared_path), 'tunnel', '--no-autoupdate',
        '--url', f"http://127.0.0.1:{config['PORT']}",
        'run', '--token', config['CF_TOKEN']
    ]
    with open(LOG_FILE, "a") as log_f:
        subprocess.Popen(cf_cmd, stdout=log_f, stderr=log_f)
    print_and_log("cloudflared tunnel started.")

# ======== 4. 主程序入口 ========

# 检查一个标记文件，防止在开发环境中重复运行
# 在 Streamlit Cloud 上，每次部署都是一个新环境，所以这个逻辑会完整执行一次
FLAG_FILE = INSTALL_DIR / ".launched"
if not FLAG_FILE.exists():
    # 运行所有服务
    run_services()
    
    # 创建标记文件，表示已经启动过
    FLAG_FILE.touch()
    
    print_and_log("All services launched. Script is now idle.")
else:
    print_and_log("Services already launched in this session. Script is idle.")

# --- 最后，用一个空白的占位符来保持 Streamlit 进程存活 ---
# 这样，我们启动的所有子进程 (sing-box, cloudflared) 就能继续在后台运行
st.empty()
# 你现在看到的这个空白页面，外界是访问不到的。
# 外界访问你的域名时，流量被 cloudflared -> sing-box 拦截并导向了伪装站。
