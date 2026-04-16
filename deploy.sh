#!/bin/bash
# ============================================================
# AWS Ubuntu Deployment Script
# Run this on your AWS Ubuntu instance
# ============================================================

set -e

echo "=================================================="
echo "  AI Video Agent — AWS Deployment"
echo "=================================================="

# --- 1. System Updates ---
echo "[1/6] Updating system..."
sudo apt-get update -y
sudo apt-get upgrade -y

# --- 2. Install Docker ---
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    echo "Docker installed. You may need to log out and back in for group changes."
else
    echo "Docker already installed."
fi

# --- 3. Install Docker Compose ---
echo "[3/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo apt-get install -y docker-compose-plugin
    # Also install standalone docker-compose
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    echo "Docker Compose already installed."
fi

# --- 4. Setup Application ---
echo "[4/6] Setting up application..."
APP_DIR="/opt/video-agent"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Copy project files (if not already there)
if [ ! -f "$APP_DIR/requirements.txt" ]; then
    echo "Please copy your project files to $APP_DIR"
    echo "Example: scp -r ./videoagent16apr/* your-aws-ip:$APP_DIR/"
    exit 1
fi

cd $APP_DIR

# --- 5. Configure Environment ---
echo "[5/6] Configuring environment..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit .env and set your DEEPSEEK_API_KEY!"
    echo "   nano $APP_DIR/.env"
    echo ""
fi

# Create logs directory
mkdir -p logs

# --- 6. Build & Run ---
echo "[6/6] Building and starting..."
sudo docker-compose down 2>/dev/null || true
sudo docker-compose up -d --build

echo ""
echo "=================================================="
echo "  ✅ Deployment Complete!"
echo "=================================================="
echo ""
echo "  API:     http://$(curl -s ifconfig.me):8000"
echo "  Health:  http://$(curl -s ifconfig.me):8000/api/health"
echo "  Docs:    http://$(curl -s ifconfig.me):8000/docs"
echo ""
echo "  Logs:    sudo docker-compose logs -f"
echo "  Stop:    sudo docker-compose down"
echo "  Restart: sudo docker-compose restart"
echo ""
