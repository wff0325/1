# -*- coding: utf-8 -*-
import os
import sys
import json
import subprocess
from pathlib import Path
import urllib.request
import ssl
import zipfile
import streamlit as st
import psutil

# ======== Streamlit 配置 ========
st.set_page_config(page_title="ArgoSB 调试面板", layout="wide")
st.title("ArgoSB 交互式调试面板")
st.warning("请按顺序点击按钮进行诊断。")

# ======== 核心变量和路径 ========
APP_ROOT = Path.cwd()
INSTALL_DIR = APP_ROOT / ".agsb"
INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# ======== 状态检查函数 ========
def check_binaries():
    """检查所需的可执行文件是否存在。"""
    files = {
        "cloudflared": (INSTALL_DIR / "cloudflared").exists(),
        "sing-box": (INSTALL_DIR / "sing-box").exists(),
    }
    if "NEZHA_SERVER" in st.secrets:
        files["nezha-agent"] = (INSTALL_DIR / "nezha-agent").exists()
    return files

def check_processes():
    """检查相关进程是否正在运行。"""
    procs = {}
    keywords = ['sing-box', 'cloudflared', 'nezha-agent']
    for proc in psutil.process_iter(['cmdline']):
        try:
            if proc.info['cmdline']:
                cmd_line = ' '.join(proc.info['cmdline'])
                for keyword in keywords:
                    if keyword in cmd_line:
                        procs[keyword] = f"Running (PID: {proc.pid})"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return procs

# ======== UI 布局 ========
st.header("1. 状态检查")
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Secrets 配置")
    with st.expander("点击查看已加载的 Secrets", expanded=False):
        # 为了安全，不直接显示敏感信息
        secrets_to_show = {k: (v[:8] + '...' if k in ['CF_TOKEN', 'NEZHA_KEY'] else v) for k, v in st.secrets.items()}
        st.json(secrets_to_show)

with col2:
    st.subheader("文件状态")
    st.write(check_binaries())

with col3:
    st.subheader("进程状态")
    st.write(check_processes())

st.header("2. 手动操作")

# --- 操作 1: 下载 ---
if st.button("下载所有必需文件"):
    with st.status("正在下载...", expanded=True) as status:
        arch = "amd64"
        
        # 下载 cloudflared
        status.update(label="正在下载 cloudflared...")
        cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
        subprocess.run(['wget', '-O', str(INSTALL_DIR / "cloudflared"), cf_url], capture_output=True)
        os.chmod(INSTALL_DIR / "cloudflared", 0o755)
        st.write("✅ cloudflared 下载完成。")

        # 下载 sing-box
        status.update(label="正在下载 sing-box...")
        sb_version = "1.9.0-beta.11"
        sb_name = f"sing-box-{sb_version}-linux-{arch}"
        sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name}.tar.gz"
        tar_path = INSTALL_DIR / "sing-box.tar.gz"
        subprocess.run(['wget', '-O', str(tar_path), sb_url], capture_output=True)
        import tarfile
        with tarfile.open(tar_path, "r:gz") as tar: tar.extractall(path=INSTALL_DIR, filter='data')
        shutil.move(INSTALL_DIR / sb_name / "sing-box", INSTALL_DIR / "sing-box")
        shutil.rmtree(INSTALL_DIR / sb_name); tar_path.unlink()
        os.chmod(INSTALL_DIR / "sing-box", 0o755)
        st.write("✅ sing-box 下载完成。")
        
        status.update(label="所有文件下载完毕！", state="complete")
    st.rerun()

# --- 操作 2: 启动 Cloudflared (关键诊断) ---
st.subheader("关键诊断：启动 Cloudflared")
st.info("这一步将直接运行`cloudflared`命令并显示所有输出。如果这里报错，说明您的 `CF_TOKEN` 极有可能是无效的。")

if st.button("运行 `cloudflared` 并显示日志"):
    if not (INSTALL_DIR / "cloudflared").exists():
        st.error("请先点击上面的按钮下载文件。")
    else:
        try:
            token = st.secrets["CF_TOKEN"]
            command = [str(INSTALL_DIR / "cloudflared"), 'tunnel', '--no-autoupdate', 'run', '--token', token]
            
            with st.spinner("正在运行 `cloudflared`..."):
                # 使用 Popen 启动并捕获输出
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # 等待几秒钟，看看是否有即时错误输出
                time.sleep(5)
                
                # 读取输出
                stdout_output = process.stdout.read()
                stderr_output = process.stderr.read()
                
                st.subheader("`cloudflared` 命令的输出:")
                if stdout_output:
                    st.text("标准输出 (stdout):")
                    st.code(stdout_output, language="log")
                if stderr_output:
                    st.text("错误输出 (stderr):")
                    st.code(stderr_output, language="log")
                
                if not stdout_output and not stderr_output:
                    st.warning("`cloudflared` 在5秒内没有任何输出就退出了。这极度表明 Token 无效。")

                # 清理掉测试进程
                process.kill()

        except KeyError:
            st.error("错误: 无法在 Secrets 中找到 `CF_TOKEN`。")
        except Exception as e:
            st.error(f"运行命令时发生未知错误: {e}")

# --- 操作 3: 清理所有进程 ---
if st.button("清理所有残留进程", type="primary"):
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
    st.success(f"清理完成！已终止 {len(killed_procs)} 个进程。")
    st.write(killed_procs)
    st.rerun()
