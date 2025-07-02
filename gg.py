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

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 终极调试面板", layout="wide")
st.title("ArgoSB 终极调试面板")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== 状态管理 ========
if 'processes' not in st.session_state:
    st.session_state.processes = {}

# ======== 辅助函数 ========
def download_with_progress(urls, target_path, status_placeholder):
    for i, url in enumerate(urls):
        try:
            status_placeholder.update(label=f"尝试下载 {Path(url).name} (来源 {i+1})...")
            ctx = ssl._create_unverified_context()
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            if target_path.suffix == '.zip':
                with zipfile.ZipFile(target_path, 'r') as zf_test:
                    if zf_test.testzip() is not None: raise ValueError("下载的ZIP文件已损坏")
            status_placeholder.update(label=f"下载成功: {target_path.name}")
            return True
        except Exception as e:
            st.warning(f"从 {url} 下载失败: {e}. 尝试下一个来源...")
    st.error(f"所有下载来源均失败: {Path(target_path).name}"); return False

def kill_all_processes():
    keywords = ['sing-box', 'cloudflared', 'nezha-agent']
    for proc in psutil.process_iter(['cmdline', 'pid']):
        try:
            if proc.info['cmdline']:
                if any(keyword in ' '.join(proc.info['cmdline']) for keyword in keywords):
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    st.session_state.processes = {}

# ======== UI 布局 ========
st.header("1. 状态检查与全局控制")
if st.button("清理所有进程并刷新页面", type="primary"):
    kill_all_processes(); st.success("清理完成！"); time.sleep(1); st.rerun()

col1, col2 = st.columns(2)
with col1:
    st.subheader("文件状态")
    files = {"cloudflared": (INSTALL_DIR / "cloudflared").exists(), "sing-box": (INSTALL_DIR / "sing-box").exists()}
    if all(k in st.secrets for k in ["NEZHA_SERVER", "NEZHA_PORT", "NEZHA_KEY"]):
        files["nezha-agent"] = (INSTALL_DIR / "nezha-agent").exists()
    st.write(files)
with col2:
    st.subheader("进程状态")
    procs_status = {name: f"Running (PID: {proc.pid})" for name, proc in st.session_state.processes.items() if proc.poll() is None}
    st.write(procs_status)

if st.button("下载/更新所有必需文件"):
    with st.status("正在下载...", expanded=True) as status:
        arch = "amd64"
        cf_urls = [f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"]
        if download_with_progress(cf_urls, INSTALL_DIR / "cloudflared", status): os.chmod(INSTALL_DIR / "cloudflared", 0o755)
        
        sb_version="1.9.0-beta.11"; sb_name=f"sing-box-{sb_version}-linux-{arch}"; tar_path=INSTALL_DIR/"sing-box.tar.gz"
        sb_urls = [f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"]
        if download_with_progress(sb_urls, tar_path, status):
            with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR, filter='data')
            shutil.move(INSTALL_DIR/sb_name/"sing-box", INSTALL_DIR/"sing-box"); shutil.rmtree(INSTALL_DIR/sb_name); tar_path.unlink(); os.chmod(INSTALL_DIR/"sing-box", 0o755)

        if all(k in st.secrets for k in ["NEZHA_SERVER", "NEZHA_PORT", "NEZHA_KEY"]):
            zip_path = INSTALL_DIR/"nezha-agent.zip"
            nezha_urls = ["https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_amd64.zip", "https://github.91chi.fun/https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_amd64.zip"]
            if download_with_progress(nezha_urls, zip_path, status):
                with zipfile.ZipFile(zip_path, 'r') as zf: zf.extractall(INSTALL_DIR);
                zip_path.unlink()
        status.update(label="操作完成！", state="complete"); time.sleep(1); st.rerun()

st.header("2. 服务独立控制与日志")
if st.button("启动所有服务"):
    kill_all_processes()
    token = st.secrets["CF_TOKEN"]; command = [str(INSTALL_DIR / "cloudflared"), 'tunnel', '--no-autoupdate', 'run', '--token', token]
    st.session_state.processes['cloudflared'] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
    
    port = int(st.secrets.get("PORT", random.randint(10000, 20000))); uuid_str = st.secrets.get("UUID", str(uuid.uuid4())); ws_path = "/"
    sb_config = {"log": {"level": "info"}, "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": port, "users": [{"uuid": uuid_str}], "transport": {"type": "ws", "path": ws_path}}], "outbounds": [{"type": "direct"}]}
    (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config))
    command = [str(INSTALL_DIR / "sing-box"), 'run', '-c', str(INSTALL_DIR / "sb.json")]
    st.session_state.processes['sing-box'] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
    
    if all(k in st.secrets for k in ["NEZHA_SERVER", "NEZHA_PORT", "NEZHA_KEY"]):
        nezha_config = {"SERVER": st.secrets["NEZHA_SERVER"], "PORT": st.secrets["NEZHA_PORT"], "KEY": st.secrets["NEZHA_KEY"], "TLS": st.secrets.get("NEZHA_TLS", False)}
        command = [str(INSTALL_DIR / "nezha-agent"), '-s', f"{nezha_config['SERVER']}:{nezha_config['PORT']}", '-p', nezha_config['KEY']]
        if nezha_config['TLS']: command.append('--tls')
        st.session_state.processes['nezha-agent'] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
    time.sleep(2); st.rerun()

st.subheader("实时日志")
log_tabs = st.tabs(["Cloudflared", "Sing-box", "Nezha Agent"])
log_outputs = {name: "" for name in ["Cloudflared", "Sing-box", "Nezha Agent"]}

for name, proc in st.session_state.get('processes', {}).items():
    if proc.stdout:
        # 非阻塞读取
        # os.set_blocking(proc.stdout.fileno(), False)
        log_outputs[name.capitalize()] = proc.stdout.read()

with log_tabs[0]: st.code(log_outputs["Cloudflared"], language="log")
with log_tabs[1]: st.code(log_outputs["Sing-box"], language="log")
with log_tabs[2]: st.code(log_outputs["Nezha Agent"], language="log")
