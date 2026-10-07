# Shuffling

Учебный проект: 2D-игра на Python + Pygame.
Состоит из трёх частей:

- **Локальная игра** (`client/`) — single-player с врагами, HUD и звуком.
- **Сетевой клиент** (`client/client.py`) — UDP-клиент для мультиплеера.
- **Сервер** (`server/server.py`) — авторитарный UDP-сервер.

## Стек

- Python 3.10+
- Pygame 2.x

## Установка

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install pygame

```
Shuffling/
├── README.md
├── shared/
│   ├── __init__.py
│   ├── config.py         # все константы
│   └── protocol.py       # строковые типы сообщений
├── server/
│   ├── __init__.py
│   └── server.py         # UDP-сервер (был "import json.txt")
└── client/
    ├── __init__.py
    ├── ui.py             # Button, draw_hud, draw_crosshair
    ├── main_menu.py      # run_menu
    ├── local_game.py     # Player, Enemy, run_game (локальная игра)
    ├── client.py         # сетевой клиент (был client.py.txt)
    └── main.py           # точка входа клиента
```