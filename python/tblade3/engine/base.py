"""Engine interface: something that runs T-Blade3 on input-file text and returns a Geometry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from ..geometry import Geometry


class Engine(ABC):
    """Runs T-Blade3 for one blade row.

    ``files`` maps input file names (e.g. "3dbgbinput.2.dat", "spancontrolinputs.2.dat") to their
    text. ``main`` is the name of the main input file among them. The engine writes the files to a
    private working folder, runs T-Blade3 there and reads the results back.

    A failed run raises ``TBlade3Error``; the engine stays usable afterwards.
    """

    @abstractmethod
    def run(self, files: Mapping[str, str], main: str, *, derivatives: bool = True) -> Geometry:
        ...

    def close(self) -> None:
        """Release the working folder and any worker process."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
