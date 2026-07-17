"""Test fixture: a plugin module that raises on import, to prove the
loader contains one plugin's failure without crashing others or the app.
"""

raise RuntimeError("this plugin is intentionally broken")
