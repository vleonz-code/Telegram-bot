#!/bin/bash
set -e

echo "================================="
echo "🚀 Deploy dimulai..."
echo "================================="

cd /root/Telegram-bot

echo "📥 Mengambil update dari GitHub..."
git fetch origin
git reset --hard origin/main

echo "🔄 Restart bot..."
systemctl restart telegram-bot

echo "✅ Memastikan bot sudah aktif..."
if systemctl is-active --quiet telegram-bot; then
    echo "✅ Bot aktif."
else
    echo "❌ Bot gagal aktif."
    exit 1
fi

echo "================================="
echo "✅ Deploy selesai."
echo "================================="
