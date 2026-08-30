#!/bin/bash
set -e

echo "Installing system dependencies (Tesseract OCR)..."
apt-get update
apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    libpoppler-cpp-dev \
    poppler-utils

echo "Installing Python dependencies..."
pip install --no-cache-dir -r requirements.txt

echo "Build complete!"
