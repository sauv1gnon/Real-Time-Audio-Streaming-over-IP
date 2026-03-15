"""Pytest configuration — add the project root to sys.path."""

import sys
import os

# Ensure the project root is on the path so that absolute imports like
# `from sip.messages import ...` work correctly.
sys.path.insert(0, os.path.dirname(__file__))
