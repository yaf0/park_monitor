#!/bin/bash
systemctl stop flask-park-monitor.service
# 设置环境变量，确保中文字符支持
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# 0、检查是否以root用户运行
if [ "$(id -u)" -ne 0 ]; then
    echo "此脚本必须以root用户运行！" 1>&2
    exit 1
fi

echo "正在安装 flask-park-monitor..."

# 1、检查 Python 3 是否安装及其版本
if ! command -v python3 &>/dev/null; then
    echo "未安装 Python 3。请安装 Python 3.6.8 或更高版本。" 1>&2
    exit 1
fi

# 检查 Python 版本是否大于等于 3.6.8
PYTHON_VERSION=$(python3 -c 'import platform; print(platform.python_version())')
REQUIRED_VERSION="3.6.8"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Python 版本必须大于等于 3.6.8。当前版本：$PYTHON_VERSION" 1>&2
    exit 1
fi

echo "已安装 Python 3，版本：$PYTHON_VERSION"

# 2.1、检查并安装 Flask
if ! python3 -c "import flask" &>/dev/null; then
    echo "Flask 未安装，正在安装 Flask..."
    pip3 install flask
    if [ $? -ne 0 ]; then
        echo "Flask 安装失败" 1>&2
        exit 1
    fi
else
    echo "Flask 已安装。"
fi

# 2.2、检查并安装 flask_compress
if ! python3 -c "import flask_compress" &>/dev/null; then
    echo "flask_compress 未安装，正在安装 flask_compress..."
    pip3 install flask_compress
    if [ $? -ne 0 ]; then
        echo "flask_compress 安装失败" 1>&2
        exit 1
    fi
else
    echo "flask_compress 已安装。"
fi

# 3、将 park_monitor 目录复制到 /opt 下
#if [ -d "/opt/park_monitor" ]; then
#    echo "/opt/park_monitor 已存在，跳过复制。"
#else
#    cp -fr park_monitor /opt
#    echo "已将 park_monitor 复制到 /opt。"
#fi

# 4、导入并加载 service 文件，使用 systemd 管理自启动和日志
cp ./flask-park-monitor.service /etc/systemd/system
chmod 644 /etc/systemd/system/flask-park-monitor.service

# 5、重新加载 systemd 配置
systemctl daemon-reload
if [ $? -ne 0 ]; then
    echo "重新加载 systemd 配置失败" 1>&2
    exit 1
fi

# 6、设置开机自启动并启动服务
systemctl enable flask-park-monitor.service
if ! systemctl start flask-park-monitor.service; then
    echo "启动 flask-park-monitor 服务失败" 1>&2
    exit 1
fi

# 7、检查服务状态
systemctl status flask-park-monitor.service

echo "应用已成功部署到/opt/park_monitor"
echo "有问题+V:yaf000"
