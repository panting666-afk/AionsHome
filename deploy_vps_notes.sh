#!/usr/bin/env bash
# AionsHome 部署脚本：同步修改和新增的文件到 VPS 并重建容器
# 用法：bash deploy_vps_notes.sh
set -e
KEY="$HOME/.ssh/aions_vps_ed25519"
HOST="root@101.132.72.215"
APP="/opt/aionshome/aion-chat"
TS=$(date +%Y%m%d%H%M%S)

echo "=====[1/6] 检查 VPS 结构 ====="
ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -i "$KEY" "$HOST" \
  "ls -d $APP $APP/routes $APP/static && echo 'VPS 目录结构 OK'"

echo "=====[2/6] 备份远端关键文件 ====="
ssh -i "$KEY" "$HOST" \
  "cd $APP && \
   cp -a database.py database.py.bak_$TS && \
   cp -a main.py main.py.bak_$TS && \
   cp -a static/home.html static/home.html.bak_$TS && \
   echo '基础备份完成'"

echo "=====[3/6] 上传全新图标 ====="
# 确保远端 public 目录存在
ssh -i "$KEY" "$HOST" "mkdir -p /opt/aionshome/public"
scp -i "$KEY" public/funIcon_notes.svg "$HOST:/opt/aionshome/public/funIcon_notes.svg"
echo "全新 SVG 图标上传成功！"

echo "=====[4/6] 上传修改/新增的文件 ====="
cd /e/AionsHome
scp -i "$KEY" aion-chat/database.py "$HOST:$APP/database.py"
scp -i "$KEY" aion-chat/main.py "$HOST:$APP/main.py"
scp -i "$KEY" aion-chat/static/home.html "$HOST:$APP/static/home.html"
scp -i "$KEY" aion-chat/routes/notes.py "$HOST:$APP/routes/notes.py"
scp -i "$KEY" aion-chat/static/notes.html "$HOST:$APP/static/notes.html"
echo "代码文件全部同步完成"

echo "=====[5/6] VPS 重建并重启容器 ====="
ssh -i "$KEY" "$HOST" \
  "cd /opt/aionshome && docker compose -f deploy/compose.yml up -d --build"

echo "=====[6/6] 健康检查 ====="
sleep 4
ssh -i "$KEY" "$HOST" \
  "code=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/manifest.json); echo \"manifest HTTP: \$code\"; docker ps --format '{{.Names}} {{.Status}}'"

echo "===== 全新 [笔记] 功能已成功部署至 VPS！快去刷新桌面看看你的精美新图标吧！ ====="
