#!/usr/bin/env bash
# Render build script for Super-Bot

set -o errexit  # Exit on error

echo "======================================"
echo "Starting Super-Bot Build Process"
echo "======================================"

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating required directories..."
mkdir -p logs
mkdir -p backups

# Initialize database
echo "Initializing database..."
python scripts/init_db.py

# Create default admin user (optional - comment out if not needed)
# echo "Creating default admin user..."
# python scripts/create_admin.py

echo "======================================"
echo "Build completed successfully!"
echo "======================================"

