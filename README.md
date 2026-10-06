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