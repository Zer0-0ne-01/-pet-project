# client/main.py
"""Точка входа сетевого клиента: меню → подключение к лобби → меню.

Сетевой клиент запускается отдельно: `python -m client.client`.
"""

import socket
import pygame

from shared.config import WIDTH, HEIGHT, FPS
from client.main_menu import run_connect_dialog, run_menu
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
        elif state == "network":
            profile = run_connect_dialog(
                screen, clock, font_button, socket.gethostname()[:16] or "player",
            )
            if profile == "__quit__":
                state = "quit"
            elif profile is not None:
                (
                    host, player_name, player_color, eyes_style, mouth_style,
                    weapon_style,
                ) = profile
                error = run_client(
                    host=host, name=player_name, color=player_color,
                    eyes_style=eyes_style, mouth_style=mouth_style,
                    weapon_style=weapon_style,
                )
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