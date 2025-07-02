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
import psutil # Import the new dependency

# ======== PYTHON-NATIVE PROCESS CLEANUP (DEFINITIVE FIX) ========
def cleanup_old_processes():
    """Kills any lingering processes from previous runs using psutil."""
    keywords = ['sing-box', 'cloudflared', 'nezha-agent']
    for proc in psutil.process_iter(['cmdline']):
        try:
            if proc.info['cmdline']:
                cmd_line = ' '.join(proc.info['cmdline'])
                if any(keyword in cmd_line for keyword in keywords):
                    proc.kill() # Terminate the process
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

# Run cleanup at the very start of the script execution
cleanup_old_processes()

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 控制面板", layout="centered")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd() 
INSTALL_DIR = APP_ROOT / ".agsb"
LOG_FILE = INSTALL_DIR / "argo.log"

# 创建安装目录
INSTALL_DIR.mkdir(parents=True, exist_ok=True)


# ======== 辅助函数 ========
def download_file(url, target_path):
    try:
        with st.spinner(f'正在下载 {Path(url).name}...'):
            ctx = ssl._create_unverified_context()
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        st.error(f"下载文件失败: {url}, 错误: {e}")
        return False

def generate_vmess_link(config_dict):
    vmess_str = json.dumps(config_dict, sort_keys=True)
    return f"vmess://{base64.b64encode(vmess_str.encode('utf-8')).decode('utf-8').rstrip('=')}"

# ======== 核心业务逻辑 ========

def load_config():
    """从 Streamlit Secrets 加载所有配置 (最终版)"""
    try:
        port_value = st.secrets.get("PORT")
        config = {
            "DOMAIN": st.secrets["DOMAIN"], "CF_TOKEN": st.secrets["CF_TOKEN"],
            "USER_NAME": st.secrets.get("USER_NAME", "default_user"),
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": int(port_value) if port_value else random.randint(10000, 20000)
        }
        # 加载带TLS开关的哪吒探针配置
        if st.secrets.get("NEZHA_SERVER") and st.secrets.get("NEZHA_PORT") and st.secrets.get("NEZHA_KEY"):
            config["NEZHA"] = {
                "SERVER": st.secrets["NEZHA_SERVER"],
                "PORT": st.secrets["NEZHA_PORT"],
                "KEY": st.secrets["NEZHA_KEY"],
                "TLS": st.secrets.get("NEZHA_TLS", False) # 关键：读取TLS开关，默认为False
            }
        return config
    except KeyError as e:
        st.error(f"错误: 缺少必要的 Secret 配置项: {e}。")
        st.stop()
    except ValueError:
        st.error(f"错误: Secrets 中的 PORT 或 NEZHA_PORT 值不是一个有效的数字。")
        st.stop()

def start_services(config):
    """在Streamlit环境中启动所有后台服务"""
    # 启动 sing-box
    if "sb_process" not in st.session_state or st.session_state.sb_process.poll() is not None:
        ws_path = f"/{config['UUID'][:8]}-vm"
        sb_config = {"log": {"level": "info"}, "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": config['PORT'], "users": [{"uuid": config['UUID']}], "transport": {"type": "ws", "path": ws_path}}], "outbounds": [{"type": "direct"}]}
        (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config))
        singbox_path = INSTALL_DIR / "sing-box"
        os.chmod(singbox_path, 0o755)
        st.session_state.sb_process = subprocess.Popen([str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")])

    # 启动 cloudflared
    if "cf_process" not in st.session_state or st.session_state.cf_process.poll() is not None:
        cloudflared_path = INSTALL_DIR / "cloudflared"
        os.chmod(cloudflared_path, 0o755)
        command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
        with open(LOG_FILE, 'w') as log_f:
            st.session_state.cf_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)

    # 启动哪吒探针 (如果已配置)
    if config.get("NEZHA"):
        if "nezha_process" not in st.session_state or st.session_state.nezha_process.poll() is not None:
            nezha_path = INSTALL_DIR / "nezha-agent"
            os.chmod(nezha_path, 0o755)
            nezha_config = config["NEZHA"]
            # 构建最终版哪吒命令
            command = [
                str(nezha_path), 
                '-s', f"{nezha_config['SERVER']}:{nezha_config['PORT']}",
                '-p', nezha_config['KEY']
            ]
            # 关键：只有当NEZHA_TLS为true时，才添加 --tls 参数
            if nezha_config['TLS']:
                command.append('--tls')
            
            st.session_state.nezha_process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def generate_links_and_save(config):
    ws_path = f"/{config['UUID'][:8]}-vm?ed=2048"
    all_links = [generate_vmess_link({"v": "2", "ps": f"VM-TLS-Direct", "add": config['DOMAIN'], "port": "443", "id": config['UUID'], "aid": "0", "net": "ws", "type": "none", "host": config['DOMAIN'], "path": ws_path, "tls": "tls", "sni": config['DOMAIN']})]
    st.session_state.links = "\n".join(all_links)
    st.session_state.installed = True
    
def install_and_run(config):
    with st.status("正在初始化服务...", expanded=True) as status:
        arch = "amd64"
        
        # 定义需要下载的文件
        required_files = {
            "sing-box": not (INSTALL_DIR / "sing-box").exists(),
            "cloudflared": not (INSTALL_DIR / "cloudflared").exists(),
        }
        if config.get("NEZHA"):
            required_files["nezha-agent"] = not (INSTALL_DIR / "nezha-agent").exists()

        # 执行下载
        if required_files.get("sing-box"):
            status.update(label="正在下载 sing-box..."); sb_version = "1.9.0-beta.11"; sb_name = f"sing-box-{sb_version}-linux-{arch}"; sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"; tar_path = INSTALL_DIR / "sing-box.tar.gz"
            if download_file(sb_url, tar_path):
                import tarfile;
                with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR, filter='data');
                shutil.move(INSTALL_DIR / sb_name / "sing-box", INSTALL_DIR / "sing-box"); shutil.rmtree(INSTALL_DIR / sb_name); tar_path.unlink()
        
        if required_files.get("cloudflared"):
            status.update(label="正在下载 cloudflared..."); cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"; download_file(cf_url, INSTALL_DIR / "cloudflared")
        
        if required_files.get("nezha-agent"):
            status.update(label="正在下载哪吒探针..."); nezha_url = "https://github.91chi.fun/https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_amd64.zip"; zip_path = INSTALL_DIR / "nezha-agent.zip"
            if download_file(nezha_url, zip_path):
                with zipfile.ZipFile(zip_path, 'r') as zf: zf.extractall(INSTALL_DIR);
                zip_path.unlink()
        
        status.update(label="正在启动后台服务...")
        start_services(config)
        
        status.update(label="正在生成节点链接...")
        generate_links_and_save(config)
        status.update(label="初始化完成！", state="complete", expanded=False)

# ======== Streamlit UI 界面 ========
st.title("ArgoSB 部署面板")
app_config = load_config()
st.session_state.app_config = app_config
st.markdown(f"**域名:** `{app_config['DOMAIN']}`")

if app_config.get("NEZHA"):
    tls_status = "启用 (TLS)" if app_config["NEZHA"]["TLS"] else "禁用 (No-TLS)"
    st.info(f"哪吒探针已配置: {tls_status}")

if "installed" in st.session_state and st.session_state.installed:
    st.success("服务已启动。")
    st.subheader("Vmess 节点链接")
    st.code(st.session_state.links, language="text")
else:
    install_and_run(app_config)
    st.rerun()

with st.expander("查看当前配置和Argo日志"):
    display_config = {k: v for k, v in app_config.items() if k not in ["CF_TOKEN", "NEZHA"]}
    if app_config.get("NEZHA"):
        display_config["NEZHA"] = {k: v for k, v in app_config["NEZHA"].items() if k != "KEY"}
    st.json(display_config)
    if LOG_FILE.exists(): st.code(LOG_FILE.read_text(), language='log')

st.markdown("---")
st.markdown("原作者: wff | 改编: AI for Streamlit")
