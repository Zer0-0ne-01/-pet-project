# client/main_menu.py
"""Главное меню: Play / Exit. Возвращает строку-действие."""

import pygame

from shared.config import WIDTH, HEIGHT, FPS, MENU_BG, UI_TEXT
from client.ui import Button


def run_menu(screen, clock, font_button):
    """Возвращает 'play' | 'quit'."""
    title_font = pygame.font.SysFont("consolas", 72, bold=True)
    hint_font = pygame.font.SysFont("consolas", 20)

    buttons = [
        Button("Играть", (WIDTH // 2 - 150, HEIGHT // 2 - 30, 300, 64),
               font_button, "play"),
        Button("Выход",  (WIDTH // 2 - 150, HEIGHT // 2 + 60, 300, 64),
               font_button, "quit"),
    ]

    while True:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "quit"

            for b in buttons:
                action = b.handle_event(event)
                if action:
                    return action

        screen.fill(MENU_BG)

        title = title_font.render("Shuffling", True, UI_TEXT)
        title_rect = title.get_rect(center=(WIDTH // 2, HEIGHT // 3))
        screen.blit(title, title_rect)

        for b in buttons:
            b.draw(screen)

        hint = hint_font.render("Мышь — выбор, Esc — выход", True, (160, 160, 180))
        hint_rect = hint.get_rect(center=(WIDTH // 2, HEIGHT - 40))
        screen.blit(hint, hint_rect)

        pygame.display.flip()