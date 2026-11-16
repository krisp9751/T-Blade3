"""Exceptions raised by the tblade3 package."""


class TBlade3Error(RuntimeError):
    """A T-Blade3 run failed (bad input, fatal error, or a crash of the engine).

    ``log`` holds the tail of T-Blade3's error and run logs when available.
    """

    def __init__(self, message: str, log: str = ""):
        super().__init__(message if not log else f"{message}\n{log}")
        self.message = message
        self.log = log

    def __reduce__(self):
        return (type(self), (self.message, self.log))


class InputFormatError(ValueError):
    """A T-Blade3 input file could not be parsed."""
