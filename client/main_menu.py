# client/main_menu.py
"""Главное меню и ввод адреса сетевого сервера."""

import pygame

from shared.config import WIDTH, HEIGHT, FPS, MENU_BG, UI_TEXT, BUTTON_BORDER
from client.ui import Button


def run_menu(screen, clock, font_button):
    """Возвращает 'play' | 'network' | 'quit'."""
    title_font = pygame.font.SysFont("consolas", 72, bold=True)
    hint_font = pygame.font.SysFont("consolas", 20)

    buttons = [
        Button("Одиночная игра", (WIDTH // 2 - 180, HEIGHT // 2 - 75, 360, 64),
               font_button, "play"),
        Button("Сетевая игра", (WIDTH // 2 - 180, HEIGHT // 2 + 5, 360, 64),
               font_button, "network"),
        Button("Выход", (WIDTH // 2 - 180, HEIGHT // 2 + 85, 360, 64),
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


def run_connect_dialog(screen, clock, font):
    """Запрашивает IP-адрес хоста; пустое значение означает этот компьютер."""
    address = ""
    hint_font = pygame.font.SysFont("consolas", 20)
    pygame.key.start_text_input()
    try:
        while True:
            clock.tick(FPS)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "__quit__"
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return None
                    if event.key == pygame.K_BACKSPACE:
                        address = address[:-1]
                    elif event.key == pygame.K_RETURN:
                        return address.strip() or "127.0.0.1"
                elif event.type == pygame.TEXTINPUT:
                    address = (address + event.text)[:64]

            screen.fill(MENU_BG)
            title = font.render("Адрес сервера", True, UI_TEXT)
            screen.blit(title, title.get_rect(center=(WIDTH // 2, HEIGHT // 3)))
            field = pygame.Rect(WIDTH // 2 - 220, HEIGHT // 2 - 30, 440, 64)
            pygame.draw.rect(screen, (50, 55, 85), field, border_radius=8)
            pygame.draw.rect(screen, BUTTON_BORDER, field, 2, border_radius=8)
            text = font.render(address or "127.0.0.1", True,
                               UI_TEXT if address else (130, 130, 150))
            screen.blit(text, text.get_rect(center=field.center))
            instructions = hint_font.render(
                "Введите IP и нажмите Enter (пусто — этот компьютер); Esc — назад",
                True, (180, 180, 200),
            )
            screen.blit(instructions, instructions.get_rect(
                center=(WIDTH // 2, HEIGHT // 2 + 70),
            ))
            pygame.display.flip()
    finally:
        pygame.key.stop_text_input()