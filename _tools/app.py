#!/usr/bin/env python3
"""Окно библиотеки картинок (PyQt6). Запуск - Library.cmd в корне библиотеки. Устройство - README.md."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.main_window import main

if __name__ == "__main__":
    main()
