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
st.set_page_config(page_title="Service Status", layout="wide")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
LOG_FILE = INSTALL_DIR / "app_run.log"
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== 辅助函数 ========
def download_file(url, target_path):
    try:
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        with open(LOG_FILE, 'a') as f: f.write(f"下载文件失败: {url}, 错误: {e}\n")
        return False

# ======== 核心业务逻辑 ========

def load_config():
    """从 Streamlit Secrets 加载配置"""
    try:
        # 必须从secrets中为UUID提供一个固定值，否则每次重启ID都会变
        config_uuid = st.secrets.get("UUID")
        if not config_uuid:
            st.error("严重错误: 您必须在 Streamlit Secrets 中设置一个固定的 'UUID'！")
            st.stop()

        return {
            "DOMAIN": st.secrets["DOMAIN"],
            "CF_TOKEN": st.secrets["CF_TOKEN"],
            "UUID": config_uuid, # 使用从secrets读取的固定UUID
            "PORT": int(st.secrets.get("PORT", random.randint(10000, 20000))),
            "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
            "NEZHA_KEY": st.secrets.get("NEZHA_KEY", ""),
            "NEZHA_TLS": str(st.secrets.get("NEZHA_TLS", True)).lower() == "true",
        }
    except KeyError as e:
        st.error(f"配置缺失: {e}")
        st.stop()

def start_services(config):
    """在Streamlit环境中启动后台服务"""
    for name in ["cloudflared", "sing-box", "nezha-agent"]:
        try:
            subprocess.run(["pkill", "-f", name], check=False)
        except FileNotFoundError: pass

    # 启动 sing-box (保持原样, 使用固定UUID)
    ws_path = f"/{config['UUID'][:8]}-vm"
    sb_config = {"log": {"level": "info", "timestamp": True}, "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": config['PORT'], "users": [{"uuid": config['UUID'], "alterId": 0}], "transport": {"type": "ws", "path": ws_path}}], "outbounds": [{"type": "direct"}]}
    (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config))
    singbox_path = INSTALL_DIR / "sing-box"
    if singbox_path.exists():
        os.chmod(singbox_path, 0o755)
        subprocess.Popen([str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 启动 cloudflared (保持原样)
    cloudflared_path = INSTALL_DIR / "cloudflared"
    if cloudflared_path.exists():
        os.chmod(cloudflared_path, 0o755)
        command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 启动哪吒探针 (使用Vmess UUID作为Device ID)
    if config.get("NEZHA_SERVER") and config.get("NEZHA_KEY"):
        nezha_agent_path = INSTALL_DIR / "nezha-agent"
        if nezha_agent_path.exists():
            os.chmod(nezha_agent_path, 0o755)
            
            # 核心逻辑：直接使用Vmess的UUID作为哪吒探针的device_id
            device_id = config['UUID']
            
            config_content = f'server: {config["NEZHA_SERVER"]}\nclient_secret: {config["NEZHA_KEY"]}\ntls: {str(config["NEZHA_TLS"]).lower()}\ndevice_id: {device_id}'
            (INSTALL_DIR / "nezha_config.yaml").write_text(config_content)
            
            command = [str(nezha_agent_path), '-c', str(INSTALL_DIR / "nezha_config.yaml")]
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def install_all(config):
    """自动化安装流程"""
    arch = "amd64"
    st.write("正在检查并安装依赖...")
    if not (INSTALL_DIR / "sing-box").exists():
        sb_version="1.9.0"; sb_name=f"sing-box-{sb_version}-linux-{arch}"; sb_url=f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"; tar_path=INSTALL_DIR/f"{sb_name}.tar.gz"
        if download_file(sb_url, tar_path): import tarfile; tar=tarfile.open(tar_path,"r:gz"); tar.extract(f"{sb_name}/sing-box",path=INSTALL_DIR); shutil.move(INSTALL_DIR/f"{sb_name}/sing-box",INSTALL_DIR/"sing-box"); tar_path.unlink(); shutil.rmtree(INSTALL_DIR/sb_name)
    if not (INSTALL_DIR / "cloudflared").exists(): download_file(f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}", INSTALL_DIR/"cloudflared")
    if config.get("NEZHA_SERVER") and not (INSTALL_DIR/"nezha-agent").exists():
        nz_url=f"https://github.com/nezhahq/agent/releases/latest/download/nezha-agent_linux_{arch}.zip"; zip_path=INSTALL_DIR/"nezha-agent.zip"
        if download_file(nz_url, zip_path): import zipfile; zip=zipfile.ZipFile(zip_path,'r'); zip.extract('nezha-agent',path=INSTALL_DIR); zip_path.unlink()
    st.write("依赖安装完成。")

# ======== 主程序入口 ========
st.title("服务部署脚本")
st.markdown("---")
# 1. 加载配置
app_config = load_config()

# 2. 显示关键诊断信息
st.subheader("诊断信息")
st.info(f"将使用以下固定UUID作为Vmess和哪吒探针的ID: `{app_config.get('UUID')}`")
st.warning("请确保这个UUID与您在哪吒面板上手动设置的Device ID完全一致！")

# 3. 安装并启动服务
with st.spinner("正在安装并启动所有服务..."):
    install_all(app_config)
    start_services(app_config)

st.success("所有服务已在后台启动！")
