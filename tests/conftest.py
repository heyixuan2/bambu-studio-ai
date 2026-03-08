"""Shared fixtures for bambu-studio-ai tests."""

import sys
import os

# Add scripts/ to path so tests can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
