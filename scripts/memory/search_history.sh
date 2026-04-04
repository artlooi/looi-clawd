#!/bin/bash
# Quick wrapper for semantic history search
# Usage: search_history.sh "your query here" [top_k]
python3 ./search_history_fast.py "$1" "${2:-7}"
