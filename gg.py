# -*- coding: utf-8 -*-
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
    """下载文件并在下载失败时记录日志"""
    try:
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        error_message = f"下载文件失败: {url}, 错误: {e}\n"
        print(error_message, file=sys.stderr)
        with open(LOG_FILE, 'a') as f:
            f.write(error_message)
        return False

# ======== 核心业务逻辑 ========

def load_config():
    """从 Streamlit Secrets 加载配置"""
    try:
        port_value = st.secrets.get("PORT")
        port = int(port_value) if port_value and port_value.isdigit() else random.randint(10000, 20000)
        
        # 确保从 secrets 读取的值都经过处理，避免 None
        config = {
            "DOMAIN": st.secrets.get("DOMAIN", ""),
            "CF_TOKEN": st.secrets.get("CF_TOKEN", ""),
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": port,
            "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
            "NEZHA_KEY": st.secrets.get("NEZHA_KEY", ""),
            "NEZHA_TLS": str(st.secrets.get("NEZHA_TLS", "true")).lower() == "true",
            "NEZHA_DEVICE_ID": st.secrets.get("NEZHA_DEVICE_ID", "") # 从 Secrets 读取，可能为空
        }
        
        # 关键配置项检查
        if not config["DOMAIN"] or not config["CF_TOKEN"]:
            st.error("关键配置缺失: 必须在 Streamlit Secrets 中设置 DOMAIN 和 CF_TOKEN。")
            st.stop()
            
        return config
    except Exception as e:
        st.error(f"加载配置时出错: {e}")
        st.stop()

def start_services(config):
    """在Streamlit环境中启动后台服务"""
    # 清理旧进程
    for name in ["cloudflared", "sing-box", "nezha-agent"]:
        try:
            # 使用 pkill -f 来确保杀死所有相关进程
            subprocess.run(["pkill", "-9", "-f", name], check=False)
        except FileNotFoundError:
            pass # 在非Linux环境中可能会找不到 pkill

    # 启动 sing-box
    ws_path = f"/{config['UUID'][:8]}-vm"
    sb_config_dict = {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": config['PORT'],
                      "users": [{"uuid": config['UUID'], "alterId": 0}],
                      "transport": {"type": "ws", "path": ws_path, "early_data_header_name": "Sec-WebSocket-Protocol"}}],
        "outbounds": [{"type": "direct"}]
    }
    (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config_dict, indent=2))
    singbox_path = INSTALL_DIR / "sing-box"
    if singbox_path.exists():
        os.chmod(singbox_path, 0o755)
        with open(LOG_FILE, 'a') as log_f:
            subprocess.Popen([str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")],
                             stdout=log_f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)

    # 启动 cloudflared
    cloudflared_path = INSTALL_DIR / "cloudflared"
    if cloudflared_path.exists():
        os.chmod(cloudflared_path, 0o755)
        command = [str(cloudflared_path), 'tunnel', '--edge-ip-version', 'auto', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
        with open(LOG_FILE, 'w') as log_f: # 'w' 模式覆盖旧日志，方便调试
            subprocess.Popen(command, stdout=log_f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)

    # 启动哪吒探针
    if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
        nezha_agent_path = INSTALL_DIR / "nezha-agent"
        if nezha_agent_path.exists():
            os.chmod(nezha_agent_path, 0o755)
            nezha_config_path = INSTALL_DIR / "nezha_config.yaml"
            device_id_file = INSTALL_DIR / "device.id"

            # ==== 这是关键的修改部分 ====
            # 1. 优先从 config (st.secrets) 获取 device_id
            persistent_device_id = config.get("NEZHA_DEVICE_ID")

            # 2. 如果 secrets 中没有，则尝试从本地文件加载
            if not persistent_device_id and device_id_file.exists():
                persistent_device_id = device_id_file.read_text().strip()

            # 3. 如果仍然没有，则生成一个新的并保存到文件
            if not persistent_device_id:
                persistent_device_id = str(uuid.uuid4())
                device_id_file.write_text(persistent_device_id)
            
            # 4. 构建包含持久化 device_id 的配置文件
            config_content = f"""
server: {config["NEZHA_SERVER"]}
client_secret: {config["NEZHA_KEY"]}
tls: {str(config["NEZHA_TLS"]).lower()}
device_id: {persistent_device_id}
"""
            with open(nezha_config_path, 'w') as f:
                f.write(config_content)
                
            command = [str(nezha_agent_path), '-c', str(nezha_config_path)]
            with open(LOG_FILE, 'a') as log_f:
                 subprocess.Popen(command, stdout=log_f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)


def install_all(config):
    """自动化安装流程"""
    arch = "amd64"
    if not (INSTALL_DIR / "sing-box").exists():
        st.write("正在安装 sing-box...")
        sb_version = "1.9.0-beta.11"
        sb_name = f"sing-box-{sb_version}-linux-{arch}"
        sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"
        tar_path = INSTALL_DIR / "sing-box.tar.gz"
        if download_file(sb_url, tar_path):
            import tarfile
            with tarfile.open(tar_path, "r:gz") as tar:
                # 确保解压到正确的目标文件
                source_path_in_tar = f"{sb_name}/sing-box"
                target_path = INSTALL_DIR / "sing-box"
                member = tar.getmember(source_path_in_tar)
                with tar.extractfile(member) as source_file, open(target_path, "wb") as dest_file:
                    shutil.copyfileobj(source_file, dest_file)
            tar_path.unlink()

    if not (INSTALL_DIR / "cloudflared").exists():
        st.write("正在安装 cloudflared...")
        cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
        download_file(cf_url, INSTALL_DIR / "cloudflared")

    if config.get("NEZHA_SERVER") and not (INSTALL_DIR / "nezha-agent").exists():
        st.write("正在安装 nezha-agent...")
        # 注意：Nezha Agent 的 release URL 可能会变，这里使用一个相对稳定的版本
        nezha_url = f"https://github.com/nezhahq/agent/releases/latest/download/nezha-agent_linux_{arch}.zip"
        zip_path = INSTALL_DIR / "nezha-agent.zip"
        if download_file(nezha_url, zip_path):
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # 直接解压出名为 'nezha-agent' 的文件
                zip_ref.extract('nezha-agent', path=INSTALL_DIR)
            zip_path.unlink()

# ======== 主程序入口 ========
with st.spinner("正在初始化和启动服务..."):
    # 1. 加载配置
    app_config = load_config()

    # 2. 安装并启动所有服务
    install_all(app_config)
    start_services(app_config)

# 3. 显示伪装的静态网页或信息
html_file = APP_ROOT / "index.html"
if html_file.exists():
    html_content = html_file.read_text(encoding="utf-8")
    st.markdown(html_content, unsafe_allow_html=True)
else:
    st.title("服务正在后台运行")
    st.markdown("---")
    st.markdown(f"**UUID:** `{app_config['UUID']}`")
    st.markdown(f"**代理路径:** `/{app_config['UUID'][:8]}-vm`")
    st.markdown(f"**域名:** `{app_config['DOMAIN']}`")
    st.info("这是一个伪装页面，核心服务已在后台启动。")
    
# 添加一个查看日志的扩展器，方便调试
with st.expander("查看运行日志 (最近20行)"):
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
                st.code("".join(lines[-20:]), language='log')
        except Exception as e:
            st.error(f"无法读取日志文件: {e}")
    else:
        st.warning("日志文件尚未创建。")
