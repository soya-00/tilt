"""Tilt core."""

__version__ = "0.2.0"
"""Reported by /status and shown in Settings.

The service and the interface are separate processes and can be different
builds — an app bundle rebuilt around a stale frozen service looks entirely
normal until something behaves like the version you thought you had replaced.
"""
