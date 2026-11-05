"""Reciprocal thermal RC discovery and identification for EnergyPlus buildings."""
from .config import Config
from .pipeline import run

__all__ = ['Config', 'run']
