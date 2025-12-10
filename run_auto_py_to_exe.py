"""run_auto_py_to_exe.py

Утилита-обёртка для запуска auto-py-to-exe из корня репозитория.
Скрипт запускает модуль auto_py_to_exe через текущий интерпретатор Python
(sys.executable). Это гарантирует, что будет использовано активное виртуальное
окружение проекта (например .venv) при запуске GUI.

Пример использования (в PowerShell из корня проекта):
    python run_auto_py_to_exe.py
или
    python run_auto_py_to_exe.py -- --help

Вариант с явным использованием интерпретатора .venv (если необходимо):
    .\.venv\Scripts\python.exe run_auto_py_to_exe.py

Дополнительные параметры после `--` будут переданы модулю auto_py_to_exe.

"""
import sys
import subprocess
import shlex
from pathlib import Path


def main():
    # Собираем аргументы для передачи модулю: всё после `--` либо все аргументы
    # (если `--` не указан) — удобно для прозрачной передачи опций.
    args = sys.argv[1:]
    forward_args = []
    if "--" in args:
        idx = args.index("--")
        forward_args = args[idx+1:]
    else:
        # если аргументы были переданы без явного `--`, передадим их тоже
        forward_args = args

    cmd = [sys.executable, "-m", "auto_py_to_exe"] + forward_args

    print("Запуск:", " ".join(shlex.quote(p) for p in cmd))
    print("Используемый интерпретатор:", sys.executable)

    try:
        # Запускаем и пересылаем stdout/err в текущий терминал
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        print("Не найден модуль auto-py-to-exe в этом окружении. Установите его командой:")
        print(f"{sys.executable} -m pip install auto-py-to-exe")
        sys.exit(2)
    except Exception as e:
        print("Ошибка при запуске auto-py-to-exe:", e)
        sys.exit(3)


if __name__ == '__main__':
    main()
