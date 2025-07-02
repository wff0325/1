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
import tarfile
import streamlit as st

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 控制面板", layout="centered")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd() 
INSTALL_DIR = APP_ROOT / ".agsb"
CF_LOG_FILE = INSTALL_DIR / "cloudflared.log"
NEZHA_LOG_FILE = INSTALL_DIR / "nezha.log"

# 创建安装目录
INSTALL_DIR.mkdir(parents=True, exist_ok=True)


# ======== 辅助函数 ========
def download_file(url, target_path, status_ui):
    try:
        status_ui.update(label=f'正在下载 {Path(url).name}...')
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        status_ui.update(label=f"下载文件失败: {url}", state="error")
        st.error(f"下载文件失败: {url}, 错误: {e}")
        st.stop()
        return False

def generate_vmess_link(config_dict):
    vmess_str = json.dumps(config_dict, sort_keys=True)
    return f"vmess://{base64.b64encode(vmess_str.encode('utf-8')).decode('utf-8').rstrip('=')}"

# ======== 核心业务逻辑 ========

def load_config():
    try:
        port_value = st.secrets.get("PORT")
        port = int(port_value) if port_value else random.randint(10000, 20000)

        config = {
            "DOMAIN": st.secrets["DOMAIN"],
            "CF_TOKEN": st.secrets["CF_TOKEN"],
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": port,
            "NEZHA_SERVER": st.secrets.get("NEZHA_SERVER", ""),
            "NEZHA_KEY": st.secrets.get("NEZHA_KEY", "")
        }
        return config
    except (KeyError, ValueError) as e:
        st.error(f"加载配置时出错: {e}。请检查您的 Secrets 设置。")
        st.stop()
    
def install_and_run():
    with st.status("正在初始化服务...", expanded=True) as status:
        if "app_config" not in st.session_state:
            st.session_state.app_config = load_config()
        config = st.session_state.app_config
        arch = "amd64"
        
        # --- 下载区 ---
        singbox_path = INSTALL_DIR / "sing-box"
        if not singbox_path.exists():
            sb_url = "https://github.com/SagerNet/sing-box/releases/download/v1.9.0-beta.11/sing-box-1.9.0-beta.11-linux-amd64.tar.gz"
            tar_path = INSTALL_DIR / "sing-box.tar.gz"
            if download_file(sb_url, tar_path, status):
                try:
                    status.update(label="正在解压 sing-box...")
                    with tarfile.open(tar_path, "r:gz") as tar: 
                        tar.extractall(path=INSTALL_DIR)
                    # 移动解压后的文件
                    extracted_folder = next(INSTALL_DIR.glob("sing-box-*-linux-amd64"))
                    shutil.move(extracted_folder / "sing-box", singbox_path)
                    shutil.rmtree(extracted_folder); tar_path.unlink()
                except Exception as e:
                    status.update(label=f"解压 sing-box 失败: {e}", state="error"); st.stop()
        
        cloudflared_path = INSTALL_DIR / "cloudflared"
        if not cloudflared_path.exists():
            cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            if not download_file(cf_url, cloudflared_path, status):
                st.stop()
        
        if config.get("NEZHA_SERVER"):
            nezha_agent_path = INSTALL_DIR / "nezha-agent"
            if not nezha_agent_path.exists():
                nezha_url = f"https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_{arch}.zip"
                zip_path = INSTALL_DIR / "nezha-agent.zip"
                if download_file(nezha_url, zip_path, status):
                    try:
                        status.update(label="正在解压 Nezha Agent...")
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            zip_ref.extractall(INSTALL_DIR)
                        zip_path.unlink()
                    except Exception as e:
                        status.update(label=f"解压 Nezha Agent 失败: {e}", state="error"); st.stop()
        
        status.update(label="正在启动后台服务...")

        # --- 服务启动区 ---
        # 启动 sing-box
        if "sb_process" not in st.session_state or st.session_state.sb_process.poll() is not None:
            ws_path = f"/{config['UUID'][:8]}-vm"
            sb_config_dict = {"log": {"level": "info", "timestamp": True}, "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": config['PORT'], "users": [{"uuid": config['UUID'], "alterId": 0}], "transport": {"type": "ws", "path": ws_path}}], "outbounds": [{"type": "direct"}]}
            (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config_dict, indent=2))
            os.chmod(singbox_path, 0o755)
            # sing-box比较稳定，直接启动
            st.session_state.sb_process = subprocess.Popen([str(singbox_path), 'run', '-c', str(INSTALL_DIR / "sb.json")])
        
        # 启动 cloudflared 并立刻检查
        if "cf_process" not in st.session_state or st.session_state.cf_process.poll() is not None:
            status.update(label="正在启动 cloudflared...")
            os.chmod(cloudflared_path, 0o755)
            command = [str(cloudflared_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
            with open(CF_LOG_FILE, 'w') as log_f:
                 st.session_state.cf_process = subprocess.Popen(command, stdout=log_f, stderr=log_f)
            
            time.sleep(5) # 给它5秒钟时间去连接或失败

            if st.session_state.cf_process.poll() is not None:
                log_content = CF_LOG_FILE.read_text()
                status.update(label=f"Cloudflared 启动失败! 请检查您的 CF_TOKEN。", state="error")
                st.error("Cloudflared 启动失败! 请检查您的 CF_TOKEN。")
                st.code(log_content, language="log")
                st.stop()
            status.update(label="cloudflared 进程已启动。")
            
        # 启动哪吒探针并立刻检查
        if config.get("NEZHA_SERVER"):
            if "nezha_process" not in st.session_state or st.session_state.nezha_process.poll() is not None:
                nezha_agent_path = INSTALL_DIR / "nezha-agent"
                if nezha_agent_path.exists():
                    status.update(label="正在启动 Nezha Agent...")
                    os.chmod(nezha_agent_path, 0o755)
                    command = [str(nezha_agent_path), '-s', config["NEZHA_SERVER"], '-p', config["NEZHA_KEY"], '--disable-force-update']
                    with open(NEZHA_LOG_FILE, 'w') as nezha_log_f:
                        st.session_state.nezha_process = subprocess.Popen(command, stdout=nezha_log_f, stderr=nezha_log_f)

                    time.sleep(5) # 给它5秒钟时间去连接或失败

                    if st.session_state.nezha_process.poll() is not None:
                        log_content = NEZHA_LOG_FILE.read_text()
                        status.update(label=f"Nezha Agent 启动失败! 请检查服务器地址和密钥。", state="error")
                        st.error("Nezha Agent 启动失败! 请检查服务器地址和密钥。")
                        st.code(log_content, language="log")
                        st.stop()
                    status.update(label="Nezha Agent 进程已启动。")

        # --- 生成链接 ---
        status.update(label="正在生成节点链接...")
        ws_path_full = f"/{config['UUID'][:8]}-vm?ed=2048"
        all_links = []
        cf_ips_tls = ["104.16.0.0", "104.18.0.0"]
        for ip in cf_ips_tls:
            all_links.append(generate_vmess_link({"v": "2", "ps": f"VM-TLS-{ip.split('.')[2]}", "add": ip, "port": "443", "id": config['UUID'],"aid": "0", "net": "ws", "type": "none", "host": config['DOMAIN'], "path": ws_path_full, "tls": "tls", "sni": config['DOMAIN']}))
        all_links.append(generate_vmess_link({"v": "2", "ps": f"VM-TLS-Direct", "add": config['DOMAIN'], "port": "443", "id": config['UUID'],"aid": "0", "net": "ws", "type": "none", "host": config['DOMAIN'], "path": ws_path_full, "tls": "tls", "sni": config['DOMAIN']}))
        st.session_state.links = "\n".join(all_links)
        
        st.session_state.installed = True
        status.update(label="初始化完成！", state="complete", expanded=False)

# ======== Streamlit UI 界面 ========
st.title("ArgoSB 部署面板")

if "installed" not in st.session_state:
    install_and_run()

config = st.session_state.get("app_config", {})
st.success("服务初始化流程已完成。")
st.markdown(f"**域名:** `{config.get('DOMAIN', 'N/A')}`")

st.subheader("Vmess 节点链接")
st.code(st.session_state.get("links", "正在生成..."), language="text")

with st.expander("查看服务状态和调试日志", expanded=True):
    st.json(config)
    
    st.subheader("Cloudflared 日志")
    if CF_LOG_FILE.exists():
        st.code(CF_LOG_FILE.read_text(), language='log')
    else:
        st.text("Cloudflared 日志文件尚未创建。")

    if config.get("NEZHA_SERVER"):
        st.subheader("Nezha Agent 日志")
        if NEZHA_LOG_FILE.exists():
            st.code(NEZHA_LOG_FILE.read_text(), language='log')
        else:
            st.text("Nezha Agent 日志文件尚未创建。")

st.markdown("---")
st.markdown("原作者: wff | 改编: AI for Streamlit")
