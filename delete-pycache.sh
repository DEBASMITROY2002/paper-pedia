#!/bin/bash
# This script finds and deletes all __pycache__ directories recursively.

find . -type d -name "__pycache__" -exec rm -r {} +

echo "All __pycache__ directories have been deleted."