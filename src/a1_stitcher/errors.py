class StitchError(Exception):
    """An actionable input, processing, or verification failure."""


class ProcessError(StitchError):
    """An external process failed or exceeded its time budget."""
