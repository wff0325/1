#!/bin/bash

npm install uuid

# 使用 Node.js 脚本生成 UUID 并赋值给环境变量
export UUID=$(node -e "const { v4: uuidv4 } = require('uuid'); console.log(uuidv4());")

# 调试输出：确认 UUID 已生成
echo "Generated UUID: $UUID"

# --- 哪吒探针配置 ---
export NEZHA_SERVER="nz1.opb.dpdns.org:80"          # 哪吒面板域名。v1 填写形式：nezha.xxx.com:8008；v0 填写形式：nezha.xxx.com
export NEZHA_PORT=""            # v1 哪吒不要填写这个。v0 哪吒 agent 端口，端口为 {443, 8443, 2096, 2087, 2083, 2053} 之一时开启 TLS
export NEZHA_KEY="sS6IUMMHEIg8Fts01i9ha4aIUJOXHeEE"             # v1 哪吒的 NZ_CLIENT_SECRET 或 v0 哪吒 agent 密钥

# --- Argo 隧道配置 ---
export ARGO_DOMAIN="phala.opb.dpdns.org"           # Argo 域名，留空即启用临时隧道
export ARGO_AUTH="eyJhIjoiZjYyNThmYzBjNDRmMmQ3MWNjNjQ0ZGQyZTQ0OGQ1YWYiLCJ0IjoiY2VkZGY5M2QtNjQ5MC00OGZkLTllMmUtMTg3ODFjNzg3YzM0IiwicyI6IlpHWmpPV0V6WWpjdE56QmxaaTAwTkROa0xXRmxOVGN0TmpBNE1qUTVPRE5pWkROaCJ9"             # Argo Token 或 json，留空即启用临时隧道

# --- 其他配置 ---
export NAME="idx"               # 节点名称
export CFIP="www.visa.com.tw" # 优选 IP 或优选域名
export CFPORT=443               # 优选 IP 或优选域名对应端口
export CHAT_ID=""               # Telegram Chat ID
export BOT_TOKEN=""             # Telegram Bot Token。需要同时填写 Chat ID 才会推送节点到 Telegram
export UPLOAD_URL=              # 节点自动推送到订阅器，需要填写部署 merge-sub 项目后的首页地址，例如：https://merge.eooce.ggff.net

# --- 执行主部署脚本 ---
# 这会下载并执行远程的 sb.sh 脚本，并使用上面设置的环境变量
bash <(curl -Ls https://main.ssss.nyc.mn/sb.sh)
