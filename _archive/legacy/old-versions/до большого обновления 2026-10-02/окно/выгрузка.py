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
from окно.общее import parallel, unique

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
    ("Для сайта: набор @1x @2x @3x (webp)", dict(fmt="webp", q=0, size=0, fit="fit", retina=True)),
    ("Под лимит Discord (самый лёгкий, до 8 МБ)", dict(fmt="best", q=0, size=0, fit="fit", budget=8000)),
    ("Наклейка для телеграма (webp 512, до 64 КБ)",
     dict(fmt="webp", q=0, size=512, fit="square", trim=True, budget=64)),
    ("Значок в svg (контуры)", dict(fmt="svg", q=0, size=0, fit="fit", trim=True)),
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
            ("Самый лёгкий (окно выберет формат)", "best"),
            ("webp", "webp"),
            ("avif", "avif"),
            ("png", "png"),
            ("jpg", "jpg"),
            ("ico", "ico"),
            ("Набор значков (ico + png + favicon)", "iconset"),
            ("svg - контуры (для плоских значков)", "svg"),
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
        self.trim = QCheckBox("Срезать прозрачные поля")
        self.retina = QCheckBox("Набор @1x @2x @3x")
        self.retina.setToolTip("name, name@2x, name@3x. Размер выше - для @1x; не задан - треть исходника.\n"
                               "Меньшие исходники не увеличиваются.")
        self.budget = QSpinBox(minimum=0, maximum=50000, singleStep=50, suffix=" КБ",
                               specialValueText="без ограничения")
        self.budget.setToolTip("Каждый файл не больше стольких КБ: снижается качество, не хватает - размер")
        self.matte = QComboBox()
        for v, t, _rgb in K.MATTES:
            self.matte.addItem(t, v)
        self.matte.setToolTip("Чем залить прозрачное в jpg")
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
        form.addRow("", self.trim)
        form.addRow("", self.retina)
        form.addRow("Не больше", self.budget)
        form.addRow("Подложка jpg", self.matte)
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
        self.trim.setChecked(o.get("trim", False))
        self.retina.setChecked(o.get("retina", False))
        self.budget.setValue(o.get("budget", 0))
        self.matte.setCurrentIndex(max(0, self.matte.findData(o.get("matte", "white"))))

    def opts(self):
        return dict(
            fmt=self.fmt.currentData(),
            q=self.q.value(),
            size=self.size.value(),
            fit=self.fit.currentData(),
            trim=self.trim.isChecked(),
            retina=self.retina.isChecked(),
            budget=self.budget.value(),
            matte=self.matte.currentData(),
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
    """Копии картинок в folder по настройкам o (как у compress + retina). Как есть и без размера -
    простое копирование; пережатие идёт по ядрам. Возвращает число выгруженных картинок."""
    os.makedirs(folder, exist_ok=True)
    n, todo = 0, []
    fmt = o.get("fmt", "")
    plain = not fmt and not o.get("size") and o.get("fit", "fit") == "fit" and not (
        o.get("trim") or o.get("retina") or o.get("budget"))
    for p in paths:
        stem, ext = os.path.splitext(os.path.basename(p))
        if p.lower().endswith(".svg") or plain:
            shutil.copy2(p, unique(os.path.join(folder, stem + ext)))
            n += 1
        elif fmt == "iconset":
            K.icon_set(K.load(p), folder, stem)
            n += 1
        else:
            todo.append((p, dict(o)))
    for i, (p, res) in enumerate(parallel(K.job_export, todo)):
        if report:
            report((n + i, len(paths), os.path.basename(p)))
        if isinstance(res, Exception):
            continue
        stem = os.path.splitext(os.path.basename(p))[0]
        for tail, f, data in res:
            with open(unique(os.path.join(folder, stem + tail + "." + f)), "wb") as fh:
                fh.write(data)
        n += 1
    return n
