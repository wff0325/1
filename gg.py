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
import streamlit as st
import psutil

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
def download_with_progress(url, target_path, status_placeholder):
    try:
        status_placeholder.update(label=f"正在下载 {Path(url).name}...")
        ctx = ssl._create_unverified_context()
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        status_placeholder.update(label=f"下载成功: {target_path.name}")
        return True
    except Exception as e:
        st.error(f"下载文件失败: {url}, 错误: {e}")
        return False

def stop_process(name):
    """停止并移除一个已记录的进程。"""
    if name in st.session_state.processes:
        try:
            proc = psutil.Process(st.session_state.processes[name].pid)
            proc.kill()
            st.toast(f"进程 {name} 已停止。")
        except psutil.NoSuchProcess:
            st.toast(f"进程 {name} 已不存在。")
        del st.session_state.processes[name]

def kill_all_processes():
    """清理所有可能残留的进程。"""
    keywords = ['sing-box', 'cloudflared', 'nezha-agent']
    killed_procs = []
    for proc in psutil.process_iter(['cmdline', 'pid']):
        try:
            if proc.info['cmdline']:
                cmd_line = ' '.join(proc.info['cmdline'])
                if any(keyword in cmd_line for keyword in keywords):
                    proc.kill()
                    killed_procs.append(cmd_line)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    # 清空 session state 中的记录
    st.session_state.processes = {}
    return killed_procs

# ======== UI 布局 ========
st.header("1. 状态检查与全局控制")

if st.button("清理所有进程并刷新页面", type="primary"):
    killed = kill_all_processes()
    st.success(f"清理完成！已终止 {len(killed)} 个进程。")
    st.write(killed)
    time.sleep(2)
    st.rerun()

# --- 文件和进程状态 ---
col1, col2 = st.columns(2)
with col1:
    st.subheader("文件状态")
    binaries = {"cloudflared": (INSTALL_DIR / "cloudflared").exists(), "sing-box": (INSTALL_DIR / "sing-box").exists()}
    if "NEZHA_SERVER" in st.secrets:
        binaries["nezha-agent"] = (INSTALL_DIR / "nezha-agent").exists()
    st.write(binaries)

with col2:
    st.subheader("进程状态")
    procs_status = {}
    for name, proc in st.session_state.processes.items():
        if proc.poll() is None:
            procs_status[name] = f"Running (PID: {proc.pid})"
        else:
            procs_status[name] = f"Stopped (Exit Code: {proc.poll()})"
    st.write(procs_status)

# --- 下载 ---
if st.button("下载/更新所有必需文件"):
    with st.status("正在下载...", expanded=True) as status:
        arch = "amd64"
        download_with_progress(f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}", INSTALL_DIR / "cloudflared", status)
        os.chmod(INSTALL_DIR / "cloudflared", 0o755)
        
        sb_version="1.9.0-beta.11"; sb_name=f"sing-box-{sb_version}-linux-{arch}"; sb_url=f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"; tar_path=INSTALL_DIR/"sing-box.tar.gz"
        if download_with_progress(sb_url, tar_path, status):
            import tarfile;
            with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR, filter='data')
            shutil.move(INSTALL_DIR/sb_name/"sing-box", INSTALL_DIR/"sing-box"); shutil.rmtree(INSTALL_DIR/sb_name); tar_path.unlink(); os.chmod(INSTALL_DIR/"sing-box", 0o755)

        if "NEZHA_SERVER" in st.secrets:
            nezha_url = "https://github.91chi.fun/https://github.com/naiba/nezha/releases/latest/download/nezha-agent_linux_amd64.zip"; zip_path = INSTALL_DIR/"nezha-agent.zip"
            if download_with_progress(nezha_url, zip_path, status):
                with zipfile.ZipFile(zip_path, 'r') as zf: zf.extractall(INSTALL_DIR);
                zip_path.unlink()
        status.update(label="所有文件就位！", state="complete")
    st.rerun()

st.header("2. 服务独立控制与日志")

# --- Cloudflared 控制 ---
st.subheader("Cloudflared Tunnel")
cf_col1, cf_col2 = st.columns(2)
with cf_col1:
    if st.button("启动 Cloudflared"):
        stop_process('cloudflared') # 先停止旧的
        token = st.secrets["CF_TOKEN"]
        command = [str(INSTALL_DIR / "cloudflared"), 'tunnel', '--no-autoupdate', 'run', '--token', token]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        st.session_state.processes['cloudflared'] = proc
        st.rerun()
with cf_col2:
    if st.button("停止 Cloudflared"):
        stop_process('cloudflared')
        st.rerun()
if 'cloudflared' in st.session_state.processes:
    with st.expander("显示 Cloudflared 日志", expanded=True):
        st.code(st.session_state.processes['cloudflared'].stdout.read(), language="log")

# --- Sing-box 控制 ---
st.subheader("Sing-box (Vmess 服务)")
sb_col1, sb_col2 = st.columns(2)
with sb_col1:
    if st.button("启动 Sing-box"):
        stop_process('sing-box')
        port = int(st.secrets.get("PORT", random.randint(10000, 20000)))
        uuid = st.secrets.get("UUID", str(uuid.uuid4()))
        ws_path = "/"
        sb_config = {"log": {"level": "info"}, "inbounds": [{"type": "vmess", "listen": "127.0.0.1", "listen_port": port, "users": [{"uuid": uuid}], "transport": {"type": "ws", "path": ws_path}}], "outbounds": [{"type": "direct"}]}
        (INSTALL_DIR / "sb.json").write_text(json.dumps(sb_config))
        command = [str(INSTALL_DIR / "sing-box"), 'run', '-c', str(INSTALL_DIR / "sb.json")]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        st.session_state.processes['sing-box'] = proc
        st.rerun()
with sb_col2:
    if st.button("停止 Sing-box"):
        stop_process('sing-box')
        st.rerun()
if 'sing-box' in st.session_state.processes:
    with st.expander("显示 Sing-box 日志", expanded=True):
        st.code(st.session_state.processes['sing-box'].stdout.read(), language="log")

# --- Nezha Agent 控制 ---
if "NEZHA_SERVER" in st.secrets:
    st.subheader("Nezha Agent")
    ne_col1, ne_col2 = st.columns(2)
    with ne_col1:
        if st.button("启动 Nezha Agent"):
            stop_process('nezha-agent')
            nezha_config = {"SERVER": st.secrets["NEZHA_SERVER"], "PORT": st.secrets["NEZHA_PORT"], "KEY": st.secrets["NEZHA_KEY"], "TLS": st.secrets.get("NEZHA_TLS", False)}
            command = [str(INSTALL_DIR / "nezha-agent"), '-s', f"{nezha_config['SERVER']}:{nezha_config['PORT']}", '-p', nezha_config['KEY']]
            if nezha_config['TLS']: command.append('--tls')
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            st.session_state.processes['nezha-agent'] = proc
            st.rerun()
    with ne_col2:
        if st.button("停止 Nezha Agent"):
            stop_process('nezha-agent')
            st.rerun()
    if 'nezha-agent' in st.session_state.processes:
        with st.expander("显示 Nezha Agent 日志", expanded=True):
            st.code(st.session_state.processes['nezha-agent'].stdout.read(), language="log")
