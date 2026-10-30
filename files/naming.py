"""
naming.py

Thread-safe human naming request.

Processor waits here.
UI provides the name.
"""

import threading


class NameRequest:

    def __init__(self):
        self.name = None
        self.preview = None
        self.event = threading.Event()
        self.regenerate_requested = False
        self.preview_version = 0
        self.default_name = None

    def request_name(self, preview, default_name=None):
        self.name = None
        self.preview = preview
        self.default_name = default_name
        self.regenerate_requested = False
        self.preview_version = 0
        self.event.clear()
        return self

    def submit(self, name: str):
        self.name = name
        self.event.set()

    def request_regenerate(self):
        self.regenerate_requested = True
        self.event.set()

    def wait(self):
        self.event.wait()
        return self.name
