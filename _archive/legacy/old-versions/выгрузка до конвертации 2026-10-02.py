"""Выгрузка копий в папку проекта: заготовки, формат, размер."""
import os
import shutil

import картинки as K
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from окно.виджеты import flat
from окно.миниатюры import lib_icon
from окно.общее import unique
from окно.сжатие import CAN

# заготовки выгрузки: имя, настройки (fmt "" - как есть, "iconset" - набор значков, q 0 - подобрать на глаз)
EXPORT_PRESETS = [
    ("Своя настройка", None),
    ("Фон для VS Code (webp, 1920)", dict(fmt="webp", q=0, size=1920, fit="fit")),
    ("Для README (webp, 1280)", dict(fmt="webp", q=0, size=1280, fit="fit")),
    ("Для сайта (avif, 1600)", dict(fmt="avif", q=0, size=1600, fit="fit")),
    (
        "Для телеграма (png 512, квадрат)",
        dict(fmt="png", q=100, size=512, fit="square"),
    ),
    (
        "Аватар (png 256, обрезать в квадрат)",
        dict(fmt="png", q=100, size=256, fit="fill"),
    ),
    (
        "Значок программы (ico + png 256 + favicon)",
        dict(fmt="iconset", q=100, size=0, fit="square"),
    ),
]


class ExportDialog(QDialog):
    """Выгрузка выбранных картинок в папку проекта: заготовки, формат, качество, размер."""

    def __init__(self, parent, n, cfg):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Выгрузить в папку: %d шт." % n)
        self.dir = QLineEdit(
            cfg.get("export_dir", ""), placeholderText="папка, куда положить копии"
        )
        pick = QPushButton(lib_icon("folder"), "")
        pick.clicked.connect(self.pick)
        row = QHBoxLayout()
        row.addWidget(self.dir, 1)
        row.addWidget(pick)
        self.preset = QComboBox()
        self.fill_presets()
        self.fmt = QComboBox()
        for t, v in (
            ("Как есть (без пережатия)", ""),
            ("webp", "webp"),
            ("avif", "avif"),
            ("png", "png"),
            ("jpg", "jpg"),
            ("ico", "ico"),
            ("Набор значков (ico + png + favicon)", "iconset"),
        ):
            self.fmt.addItem(t, v)
        self.q = QSpinBox(
            minimum=0, maximum=100, suffix=" %", specialValueText="подобрать на глаз"
        )
        self.q.setToolTip(
            "0 - окно само подберёт качество без видимой разницы; 100 - без потерь"
        )
        self.size = QSpinBox(
            minimum=0,
            maximum=8192,
            singleStep=64,
            suffix=" px",
            specialValueText="не менять",
        )
        self.size.setToolTip(
            "Длинная сторона; меньшие картинки не увеличиваются (кроме квадрата и обрезки)"
        )
        self.fit = QComboBox()
        for v, t in K.FITS:
            self.fit.addItem(t, v)
        self.open_after = QCheckBox("Открыть папку после выгрузки")
        self.open_after.setChecked(cfg.get("export_open", True))
        save_p = flat("Сохранить как заготовку...", self.save_preset)
        form = QFormLayout()
        form.addRow("Заготовка", self.preset)
        form.addRow("Папка", row)
        form.addRow("Формат", self.fmt)
        form.addRow("Качество", self.q)
        form.addRow("Размер", self.size)
        form.addRow("Как", self.fit)
        form.addRow("", self.open_after)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Выгрузить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(save_p)
        bottom.addStretch(1)
        bottom.addWidget(bb)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addLayout(bottom)
        self.resize(520, 0)
        last = cfg.get("export", dict(fmt="", q=0, size=0, fit="fit"))
        self.set_opts(last)
        self.preset.setCurrentIndex(
            max(0, self.preset.findText(cfg.get("export_preset", "")))
        )
        self.preset.currentIndexChanged.connect(self.apply_preset)

    def presets(self):
        return EXPORT_PRESETS + [
            (k, v) for k, v in self.cfg.get("export_presets", {}).items()
        ]

    def fill_presets(self):
        self.preset.clear()
        for name, _o in self.presets():
            self.preset.addItem(name)

    def set_opts(self, o):
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(o.get("fmt", ""))))
        self.q.setValue(o.get("q", 0))
        self.size.setValue(o.get("size", 0))
        self.fit.setCurrentIndex(max(0, self.fit.findData(o.get("fit", "fit"))))

    def opts(self):
        return dict(
            fmt=self.fmt.currentData(),
            q=self.q.value(),
            size=self.size.value(),
            fit=self.fit.currentData(),
        )

    def apply_preset(self):
        o = dict(self.presets())[self.preset.currentText()]
        if o:
            self.set_opts(o)

    def save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Заготовка выгрузки", "Название, например «Для игры (png 128)»:"
        )
        name = name.strip()
        if ok and name:
            self.cfg.setdefault("export_presets", {})[name] = self.opts()
            self.fill_presets()
            self.preset.setCurrentText(name)

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "Куда выгрузить", self.dir.text())
        if d:
            self.dir.setText(os.path.normpath(d))

    def accept(self):
        if not self.dir.text().strip():
            self.pick()
            if not self.dir.text().strip():
                return
        self.cfg.update(
            export_dir=self.dir.text().strip(),
            export=self.opts(),
            export_preset=self.preset.currentText(),
            export_open=self.open_after.isChecked(),
        )
        super().accept()


def export(paths, folder, o, report=None):
    """Копии картинок в folder по настройкам o (fmt, q, size, fit). Как есть и без размера - простое копирование."""
    os.makedirs(folder, exist_ok=True)
    n = 0
    for i, p in enumerate(paths):
        if report:
            report((i, len(paths), os.path.basename(p)))
        stem, ext = os.path.splitext(os.path.basename(p))
        fmt = o.get("fmt", "")
        if p.lower().endswith(".svg") or (
            not fmt and not o.get("size") and o.get("fit", "fit") == "fit"
        ):
            shutil.copy2(p, unique(os.path.join(folder, stem + ext)))
        elif fmt == "iconset":
            K.icon_set(K.load(p), folder, stem)
        else:
            f = fmt or K.fmt_of(p)
            if f not in CAN + ("ico",):
                f = "png"
            q = o.get("q", 0)
            data, _q = K.compress(
                K.load(p),
                dict(
                    fmt=f,
                    q=q,
                    lossless=q >= 100,
                    size=o.get("size", 0),
                    fit=o.get("fit", "fit"),
                ),
            )
            with open(unique(os.path.join(folder, stem + "." + f)), "wb") as fh:
                fh.write(data)
        n += 1
    return n
