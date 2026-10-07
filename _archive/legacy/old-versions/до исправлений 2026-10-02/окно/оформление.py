"""Тёмная тема окна: цвета (C), стили (QSS) и svg-стрелки для них.
Цвета заданы один раз в C: и стили, и рисовальщики плиток берут их отсюда."""
import os
import re

from окно.общее import UI

# ---------------------------------------------------------------- цвета
C = dict(
    bg0="#0d0d13",          # окно
    bg1="#14141c",          # панели
    bg2="#1b1b26",          # поля, карточки
    bg3="#242432",          # наведение
    line="#252533",
    line2="#343448",
    text="#eceaf6",
    dim="#8e8ba6",
    faint="#5d5b70",
    acc="#a897ff",          # главный акцент
    acc2="#ff8ac9",         # второй конец градиента
    teal="#5ee0d0",         # третье пятно живого фона
    accd="#2f2950",         # выделение (приглушённый акцент)
    ink="#120f1f",          # текст на акцентной кнопке
)
GRAD = "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 $acc,stop:1 $acc2)"
SOFT = "qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(168,151,255,0.30),stop:1 rgba(255,138,201,0.10))"

SVG = {
    "down": '<path d="M2.5 4l3.5 3.5 3.5-3.5" fill="none" stroke="#b9b6c8" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
    "up": '<path d="M2.5 8l3.5-3.5 3.5 3.5" fill="none" stroke="#b9b6c8" stroke-width="1.6" '
          'stroke-linecap="round" stroke-linejoin="round"/>',
    "right": '<path d="M4.5 2.5l3.5 3.5-3.5 3.5" fill="none" stroke="#8a879a" stroke-width="1.6" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
    "check": '<path d="M2.6 6.3l2.3 2.3 4.5-5" fill="none" stroke="#120f1f" stroke-width="1.9" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
}

# $имя - цвет из C, $grad / $soft - градиенты, @UI - папка со стрелками
_QSS = """
QWidget{color:$text;font:10pt "Segoe UI"}
QDialog,QMessageBox,QInputDialog{background:$bg0}
QMainWindow{background:transparent}
QLabel,QCheckBox,QRadioButton{background:transparent}
QToolTip{background:$bg3;color:$text;border:1px solid $line2;border-radius:6px;padding:5px 8px}

/* панели */
QListWidget,QTreeWidget{background:$bg1;border:1px solid $line;border-radius:14px;padding:6px;outline:0}
QWidget#panel{background:$bg1;border:1px solid $line;border-radius:14px}
QScrollArea{background:transparent;border:0}
QScrollArea>QWidget>QWidget{background:transparent}
QGroupBox{background:$bg1;border:1px solid $line;border-radius:14px;margin-top:14px;padding:12px 8px 8px 8px}
QGroupBox::title{subcontrol-origin:margin;left:14px;top:2px;color:$dim;font-weight:600}
QFrame#drop{border:2px dashed $line2;border-radius:18px;background:$bg1}

/* поля ввода */
QLineEdit,QSpinBox,QComboBox{background:$bg2;border:1px solid $line;border-radius:10px;padding:4px 10px;min-height:19px}
QLineEdit:hover,QSpinBox:hover,QComboBox:hover{border-color:$line2;background:$bg3}
QLineEdit:focus,QSpinBox:focus,QComboBox:focus{border-color:$acc}
QLineEdit:disabled,QSpinBox:disabled,QComboBox:disabled{color:$faint;background:$bg1}
QLineEdit#search{border-radius:17px;padding-left:6px;min-height:22px}
QComboBox::drop-down{border:0;width:26px}
QComboBox::down-arrow{image:url(@UI/down.svg);width:12px;height:12px}
QComboBox QAbstractItemView{background:$bg2;border:1px solid $line2;border-radius:8px;selection-background-color:$accd;outline:0;padding:4px}
QSpinBox{padding-right:26px}
QSpinBox::up-button,QSpinBox::down-button{subcontrol-origin:border;width:24px;border:0;border-left:1px solid $line;background:transparent}
QSpinBox::up-button{subcontrol-position:top right;border-top-right-radius:10px}
QSpinBox::down-button{subcontrol-position:bottom right;border-bottom-right-radius:10px}
QSpinBox::up-button:hover,QSpinBox::down-button:hover{background:$line2}
QSpinBox::up-arrow{image:url(@UI/up.svg);width:12px;height:12px}
QSpinBox::down-arrow{image:url(@UI/down.svg);width:12px;height:12px}
QSpinBox::up-arrow:disabled,QSpinBox::up-arrow:off,QSpinBox::down-arrow:disabled,QSpinBox::down-arrow:off{image:none}

/* кнопки */
QPushButton{background:$bg2;border:1px solid $line;border-radius:10px;padding:7px 14px}
QPushButton:hover{background:$bg3;border-color:$acc}
QPushButton:pressed{background:$accd}
QPushButton:disabled{color:$faint;border-color:$line;background:$bg1}
QPushButton#primary{background:$grad;color:$ink;font-weight:700;border:0;padding:9px 14px}
QPushButton#primary:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #bcafff,stop:1 #ffa3d6)}
QPushButton#primary:disabled{background:$accd;color:$faint}
QPushButton#flat,QPushButton#ghost{background:transparent;border-color:transparent;color:$dim}
QPushButton#flat{padding:3px 8px}
QPushButton#flat:hover,QPushButton#ghost:hover{color:$text;background:$bg3;border-color:$line}
QPushButton#tool{padding:7px 9px;border-radius:10px}
QPushButton#undo{background:$accd;border-color:$acc;padding:2px 10px;border-radius:8px}

/* галочки */
QCheckBox{spacing:8px}
QCheckBox::indicator,QListWidget::indicator{width:16px;height:16px;border:1px solid $line2;border-radius:5px;background:$bg2}
QCheckBox::indicator:hover,QListWidget::indicator:hover{border-color:$acc}
QCheckBox::indicator:checked,QListWidget::indicator:checked{background:$acc;border-color:$acc;image:url(@UI/check.svg)}

/* вкладки - таблетки */
QTabWidget::pane{border:0}
QTabBar{background:transparent}
QTabBar::tab{padding:7px 18px;margin:8px 3px 6px 3px;background:transparent;border-radius:10px;color:$dim}
QTabBar::tab:hover{color:$text;background:rgba(255,255,255,0.05)}
QTabBar::tab:selected{background:transparent;color:#ffffff;font-weight:600}
QTabBar::tab:selected:hover{background:transparent}

/* строки списков и дерева */
QListWidget::item{border-radius:10px;padding:4px}
QTreeWidget::item{padding:5px 2px}
QTreeWidget::item:first{border-top-left-radius:8px;border-bottom-left-radius:8px}
QTreeWidget::item:last{border-top-right-radius:8px;border-bottom-right-radius:8px;padding-right:8px}
QListWidget::item:hover,QTreeWidget::item:hover{background:$bg3}
QListWidget::item:selected{background:$soft;color:#ffffff}
QTreeWidget::item:selected{background:$accd;color:#ffffff}
QTreeView::branch,QTreeView::branch:selected,QTreeView::branch:hover{background:$bg1}
QTreeView::branch:has-children:closed{image:url(@UI/right.svg)}
QTreeView::branch:has-children:open{image:url(@UI/down.svg)}

/* полосы прокрутки, ползунок, разделители */
QScrollBar:vertical{background:transparent;width:8px;margin:4px 1px}
QScrollBar:horizontal{background:transparent;height:8px;margin:1px 4px}
QScrollBar::handle{background:$line2;border-radius:3px;min-height:32px;min-width:32px}
QScrollBar::handle:hover{background:$acc}
QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0;border:0}
QScrollBar::add-page,QScrollBar::sub-page{background:transparent}
QSlider{background:transparent}
QSlider::groove:horizontal{height:4px;background:$line2;border-radius:2px}
QSlider::sub-page:horizontal{background:$grad;border-radius:2px}
QSlider::handle:horizontal{width:14px;height:14px;margin:-5px 0;border-radius:7px;background:#ffffff;border:3px solid $acc}
QSplitter::handle{background:transparent}
QSplitter::handle:horizontal{width:8px}
QSplitter::handle:vertical{height:8px}
QSplitter::handle:hover{background:$accd;border-radius:3px}

/* строка состояния и подписи */
QStatusBar{background:transparent;color:$dim;border-top:1px solid rgba(255,255,255,0.05)}
QStatusBar::item{border:0}
QStatusBar QLabel{color:$dim;padding:0 6px}
QLabel#dim{color:$dim}
QLabel#faint{color:$faint;font-size:8pt;font-weight:700;letter-spacing:1px}
QLabel#title{font-size:16pt;font-weight:700}
QLabel#big{font-size:12pt;font-weight:600}
QLabel#head{font-size:13pt;font-weight:700}
QLabel#chip{background:$bg3;border-radius:8px;padding:3px 9px;color:$text;font-size:9pt}
QLabel#pic{background:$bg2;border:1px solid $line;border-radius:12px}
QLabel#overlay{background:rgba(13,13,19,230);border:3px dashed $acc;border-radius:22px;color:$text;font-size:17pt;font-weight:700}

/* меню */
QMenu{background:$bg2;border:1px solid $line2;border-radius:10px;padding:6px}
QMenu::item{padding:6px 22px 6px 14px;border-radius:6px}
QMenu::item:selected{background:$accd}
QMenu::separator{height:1px;background:$line;margin:5px 8px}
"""


def build_qss():
    text = _QSS.replace("$grad", GRAD).replace("$soft", SOFT)
    return re.sub(r"\$(\w+)", lambda m: C[m.group(1)], text)


QSS = build_qss()


def ui_files():
    """Пишет svg-стрелки для стилей (один раз) и возвращает путь к ним в виде для QSS."""
    os.makedirs(UI, exist_ok=True)
    for name, body in SVG.items():
        text = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">%s</svg>' % body
        p = os.path.join(UI, name + ".svg")
        try:
            with open(p, encoding="utf-8") as fh:
                if fh.read() == text:
                    continue
        except OSError:
            pass
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    return UI.replace("\\", "/")
