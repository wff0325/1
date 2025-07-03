# -- coding: utf-8 --
import os
import sys
import json
import random
import time
import shutil
import re
import base64
import socket
import subprocess
import platform
from datetime import datetime
import uuid
from pathlib import Path
import urllib.request
import ssl
import zipfile
import streamlit as st

# ======== Streamlit 配置 ========
st.set_page_config(page_title="Not Found", layout="wide")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
LOG_FILE = INSTALL_DIR / "argo.log"

# 创建安装目录
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== 辅助函数 ========
def download_file(url, target_path):
    """下载文件到指定路径"""
    try:
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        with open(LOG_FILE, 'a') as f:
            f.write(f"下载文件失败: {url}, 错误: {e}\n")
        return False

# ======== 核心业务逻辑 ========
def load_config():
    """从 Streamlit Secrets 加载配置"""
    try:
        port_value = st.secrets.get("PORT")
        port = int(port_value) if port_value else random.randint(10000, 20000)
        config = {
            "DOMAIN": st.secrets["DOMAIN"],
            "CF_TOKEN": st.secrets["CF_TOKEN"],
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": port,
            "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
            "NEZHA_KEY": st.secrets.get("NEZHA_KEY", ""),
            "NEZHA_TLS": str(st.secrets.get("NEZHA_TLS", True)).lower() == "true",
            # ==== 代码修改处 #1 ====
            # 从 Secrets 中读取永久的设备ID，使用正确的变量名 NEZHA_DEVICE_ID
            "NEZHA_DEVICE_ID": st.secrets.get("NEZHA_DEVICE_ID", "")
        }
        return config
    except KeyError as e:
        st.error(f"Application configuration is missing: {e}")
        st.stop()
    except ValueError:
        st.error("Invalid PORT configuration.")
        st.stop()

def start_services(config):
    """在Streamlit环境中启动后台服务"""
    # 清理旧进程
    for name in ["cloudflared", "sing-box", "nezha-agent"]:
        try:
            subprocess.run(["pkill", "-f", name], check=False)
        except FileNotFoundError:
            pass

    # 启动 sing-box
    ws_path = f"/{config['UUID'][:8]}-vm"
    sb_config_dict = {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": config['PORT'],
                      "users": [{"uuid": config['UUID'], "alterId": 0}],
                      "transport": {"type": "ws", "path": ws_path}}],
        "outbounds": [{"type": "direct"}]
    }
    (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config_dict, indent=2))
    singbox_path = INSTALL_DIR / "sing-box"
    if singbox_path.exists():
        os.chmod(singbox_path, 0o755)
        with open(LOG_FILE, 'a') as log_f:
            subprocess.Popen([str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")], stdout=log_f, stderr=log_f)

    # 启动 cloudflared
    cloudflared_path = INSTALL_DIR / "cloudflared"
    if cloudflared_path.exists():
        os.chmod(cloudflared_path, 0o755)
        command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
        with open(LOG_FILE, 'w') as log_f:
            subprocess.Popen(command, stdout=log_f, stderr=log_f)

    # 启动哪吒探针
    if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
        nezha_agent_path = INSTALL_DIR / "nezha-agent"
        if nezha_agent_path.exists():
            os.chmod(nezha_agent_path, 0o755)
            nezha_config_path = INSTALL_DIR / "nezha_config.yaml"
            
            # ==== 代码修改处 #2 ====
            # 在配置文件中加入经过核实的、正确的 device_id 字段
            config_content = f"""server: {config["NEZHA_SERVER"]}
client_secret: {config["NEZHA_KEY"]}
tls: {str(config["NEZHA_TLS"]).lower()}
"""
            # 只有当用户配置了 DEVICE_ID 时，才将该字段写入配置文件
            if config["NEZHA_DEVICE_ID"]:
                config_content += f'device_id: {config["NEZHA_DEVICE_ID"]}\n'
            
            with open(nezha_config_path, 'w') as f:
                f.write(config_content)
            
            command = [str(nezha_agent_path), '-c', str(nezha_config_path)]
            with open(LOG_FILE, 'a') as log_f:
                 subprocess.Popen(command, stdout=log_f, stderr=log_f)

def install_all(config):
    """自动化安装流程"""
    arch = "amd64"
    if not (INSTALL_DIR / "sing-box").exists():
        sb_version = "1.9.0-beta.11"
        sb_name = f"sing-box-{sb_version}-linux-{arch}"
        sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"
        tar_path = INSTALL_DIR / "sing-box.tar.gz"
        if download_file(sb_url, tar_path):
            import tarfile
            with tarfile.open(tar_path, "r:gz") as tar:
                source_file = tar.extractfile(f"{sb_name}/sing-box")
                with open(INSTALL_DIR / "sing-box", "wb") as dest_file:
                    if source_file:
                        shutil.copyfileobj(source_file, dest_file)
            tar_path.unlink()
    
    if not (INSTALL_DIR / "cloudflared").exists():
        cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
        download_file(cf_url, INSTALL_DIR / "cloudflared")

    if config.get("NEZHA_SERVER") and not (INSTALL_DIR / "nezha-agent").exists():
        nezha_url = f"https://github.com/nezhahq/agent/releases/latest/download/nezha-agent_linux_{arch}.zip"
        zip_path = INSTALL_DIR / "nezha-agent.zip"
        if download_file(nezha_url, zip_path):
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # 假设压缩包内主程序名为 'nezha-agent'
                zip_ref.extract('nezha-agent', INSTALL_DIR)
            zip_path.unlink()

# ======== 主程序入口 ========

# 1. 加载配置
app_config = load_config()

# 2. 安装并启动所有服务
install_all(app_config)
start_services(app_config)

# 3. 显示伪装的静态网页
html_file = Path("index.html")
if html_file.exists():
    html_content = html_file.read_text(encoding="utf-8")
    st.markdown(html_content, unsafe_allow_html=True)
else:
    st.markdown("<h1>404 Not Found</h1>", unsafe_allow_html=True)
