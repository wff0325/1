# -*- coding: utf-8 -*-
import os
import sys
import json
import subprocess
import time
import shutil
from pathlib import Path
import urllib.request
import ssl
import zipfile
import tarfile
import streamlit as st
import psutil
import random
import uuid

# ======== 进程清理 (已被验证的必要修复) ========
def cleanup_old_processes():
    keywords = ['sing-box', 'cloudflared'] # 只关心这两个核心进程
    for proc in psutil.process_iter(['cmdline']):
        try:
            if proc.info['cmdline'] and any(keyword in ' '.join(proc.info['cmdline']) for keyword in keywords):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
cleanup_old_processes()

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 运行面板", layout="centered")
st.title("ArgoSB 运行面板")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
INSTALL_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = INSTALL_DIR / "cloudflared.log"

# ======== 辅助函数 ========
def download_file(url, target_path, status_placeholder):
    try:
        status_placeholder.update(label=f"正在下载 {Path(url).name}...")
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        st.error(f"下载失败: {e}"); return False

def generate_vmess_link(config_dict):
    return f"vmess://{base64.b64encode(json.dumps(config_dict, sort_keys=True).encode('utf-8')).decode('utf-8').rstrip('=')}"

# ======== 核心业务逻辑 (全自动) ========
def install_and_run():
    # 1. 加载配置
    try:
        config = {
            "DOMAIN": st.secrets["DOMAIN"], "CF_TOKEN": st.secrets["CF_TOKEN"],
            "UUID": st.secrets.get("UUID") or str(uuid.uuid4()),
            "PORT": int(st.secrets.get("PORT", random.randint(10000, 20000)))
        }
    except (KeyError, ValueError) as e:
        st.error(f"Secrets配置错误: {e}"); st.stop()

    # 2. 显示基本信息
    st.info(f"域名 (Domain): `{config['DOMAIN']}`")
    st.info(f"UUID: `{config['UUID']}`")
    
    # 3. 下载依赖
    with st.status("正在检查并下载依赖...", expanded=True) as status:
        arch = "amd64"
        # 下载 cloudflared
        cf_path = INSTALL_DIR / "cloudflared"
        if not cf_path.exists():
            if download_file(f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}", cf_path, status):
                os.chmod(cf_path, 0o755)
        
        # 下载 sing-box
        sb_path = INSTALL_DIR / "sing-box"
        if not sb_path.exists():
            sb_version="1.9.0-beta.11"; sb_name=f"sing-box-{sb_version}-linux-{arch}"; tar_path=INSTALL_DIR/f"{sb_name}.tar.gz"
            if download_file(f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz", tar_path, status):
                with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR, filter='data')
                shutil.move(INSTALL_DIR/sb_name/"sing-box", sb_path); shutil.rmtree(INSTALL_DIR/sb_name); tar_path.unlink(); os.chmod(sb_path, 0o755)

        status.update(label="依赖已就位！", state="complete", expanded=False)

    # 4. 启动服务 (使用文件日志)
    # 启动 Cloudflared
    with open(LOG_FILE, 'w') as log_f:
        command = [str(cf_path), 'tunnel', '--no-autoupdate', 'run', '--token', config['CF_TOKEN']]
        subprocess.Popen(command, stdout=log_f, stderr=subprocess.STDOUT)
    
    # 启动 Sing-box
    ws_path = "/"; sb_config = {"log":{"level":"info"}, "inbounds":[{"type":"vmess", "listen":"127.0.0.1", "listen_port":config['PORT'], "users":[{"uuid":config['UUID']}], "transport":{"type":"ws", "path":ws_path}}], "outbounds":[{"type":"direct"}]}
    (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config))
    command = [str(sb_path), 'run', '-c', str(INSTALL_DIR / "sb.json")]
    subprocess.Popen(command) # sing-box日志我们暂时不关心

    # 5. 生成并显示链接
    st.success("服务已启动！")
    st.subheader("Vmess 节点链接")
    ws_path = "/" # 使用最简单的根路径
    links = []
    links.append(generate_vmess_link({"v":"2", "ps":f"VM-TLS-Domain", "add":config['DOMAIN'], "port":"443", "id":config['UUID'], "aid":"0", "net":"ws", "type":"none", "host":config['DOMAIN'], "path":ws_path, "tls":"tls", "sni":config['DOMAIN']}))
    links.append(generate_vmess_link({"v":"2", "ps":f"VM-TLS-IP", "add":"104.21.2.19", "port":"443", "id":config['UUID'], "aid":"0", "net":"ws", "type":"none", "host":config['DOMAIN'], "path":ws_path, "tls":"tls", "sni":config['DOMAIN']}))
    st.code("\n".join(links), language="text")

    # 6. 显示Cloudflared日志
    with st.expander("显示 Cloudflared 隧道日志"):
        # 等待日志文件生成
        for _ in range(5):
            if LOG_FILE.exists(): break
            time.sleep(1)
        
        if LOG_FILE.exists():
            st.code(LOG_FILE.read_text(), language="log")
        else:
            st.warning("Cloudflared 日志文件尚未生成。")

# --- 主执行流程 ---
if "services_started" not in st.session_state:
    install_and_run()
    st.session_state.services_started = True
else:
    st.info("服务应已在后台运行。如果连接有问题，请尝试重启应用。")
    # 为了防止每次刷新都重新显示，这里可以只显示链接
    try:
        uuid_str = st.secrets.get("UUID") or "你的UUID" # 简单回显
        domain = st.secrets["DOMAIN"]
        ws_path = "/"
        links = []
        links.append(generate_vmess_link({"v":"2", "ps":f"VM-TLS-Domain", "add":domain, "port":"443", "id":uuid_str, "aid":"0", "net":"ws", "type":"none", "host":domain, "path":ws_path, "tls":"tls", "sni":domain}))
        links.append(generate_vmess_link({"v":"2", "ps":f"VM-TLS-IP", "add":"104.21.2.19", "port":"443", "id":uuid_str, "aid":"0", "net":"ws", "type":"none", "host":domain, "path":ws_path, "tls":"tls", "sni":domain}))
        st.code("\n".join(links), language="text")
        
        with st.expander("显示 Cloudflared 隧道日志"):
             if LOG_FILE.exists():
                st.code(LOG_FILE.read_text(), language="log")
    except:
        st.error("无法从Secrets加载配置以重新显示链接。")
