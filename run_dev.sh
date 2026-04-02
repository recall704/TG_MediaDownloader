#!/bin/bash
# TG Media Downloader - Development Runner
# This script runs the bot locally with auto-reload enabled

echo "Starting TG Media Downloader (Development Mode with --reload)..."

uv run --group dev python tg_downloader.py --reload
