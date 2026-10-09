"""Отпечатки в окне: то же, что library.signatures, но пересчёт идёт в фоне и не держит окно."""

from library import signatures
from library.signatures import build_sigs
from ui.common import bg


class SigIndex(signatures.SigIndex):
    def refresh(self):
        if self.busy:
            self.again = True
            return
        self.busy = True
        old = dict(self.data)
        bg(lambda: build_sigs(old, self.lib), self._built)
