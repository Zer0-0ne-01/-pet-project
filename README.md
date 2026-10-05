# Shuffling

Учебный проект: многопользовательская 2D-игра с видом сбоку на Python + Pygame.
Сейчас на стадии «базовые кирпичики»: локальная игра с одним игроком, врагами
и счётчиком очков, плюс каркас UDP-клиента и UDP-сервера для будущего мультиплеера.

## Стек

- Python 3.10+
- Pygame 2.x

## Установка

```bash
git clone <url-репозитория>
cd Shuffling

python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install pygame