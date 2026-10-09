"""Поиск по смыслу в окне: то же, что library.semantic, но досчёт новых картинок идёт в фоне,
а ход виден в строке состояния."""

from library import semantic
from ui.common import bg, in_main


class SemIndex(semantic.SemIndex):
    def refresh(self, step=None):
        if not self.ok:
            return
        if self.busy:
            self.again = True
            return
        self.busy = True
        old = dict(self.data)
        bg(lambda: self._build(old, lambda prog: in_main(self._step, prog)), self._built)
