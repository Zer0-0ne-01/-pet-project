# client/main.py
"""Точка входа клиента: меню → локальная игра → меню → …

Сетевой клиент запускается отдельно: `python -m client.client`.
"""

import socket
import pygame

from shared.config import WIDTH, HEIGHT, FPS
from client.main_menu import run_connect_dialog, run_menu
from client.local_game import run_game
from client.client import run_client


def main():
    pygame.init()

    # Аудио инициализируем отдельно — если нет звуковой карты,
    # игра должна продолжать работать.
    try:
        pygame.mixer.init()
    except pygame.error as e:
        print(f"[AUDIO] mixer init failed: {e}")

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Shuffling")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 22)
    font_button = pygame.font.SysFont("consolas", 30, bold=True)

    state = "menu"
    while state != "quit":
        if state == "menu":
            state = run_menu(screen, clock, font_button)
        elif state == "play":
            state = run_game(screen, clock, font)
        elif state == "network":
            host = run_connect_dialog(screen, clock, font_button)
            if host == "__quit__":
                state = "quit"
            elif host is not None:
                error = run_client(host=host, name=socket.gethostname()[:16] or "player")
                if error == "__quit__":
                    state = "quit"
                else:
                    state = "menu"
                if error and error != "__quit__":
                    print(f"[CLIENT] {error}")
            else:
                state = "menu"

    pygame.quit()


if __name__ == "__main__":
    main()