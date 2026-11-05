"""Allow `python -m app.postcall` to start the post-call processor."""

from app.postcall.processor import postcall_entry

postcall_entry()
