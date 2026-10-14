# client/main_menu.py
"""Главное меню и ввод адреса сетевого сервера."""

import pygame

from shared.config import (
    WIDTH, HEIGHT, FPS, MENU_BG, UI_TEXT, BUTTON_BORDER, NET_COLORS,
)
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


def run_connect_dialog(screen, clock, font, default_name="player"):
    """Запрашивает адрес, ник и цвет до подключения к лобби."""
    address = ""
    name = default_name[:16] or "player"
    selected_color = 0
    active_field = "address"
    hint_font = pygame.font.SysFont("consolas", 20)
    small_font = pygame.font.SysFont("consolas", 16)
    address_rect = pygame.Rect(WIDTH // 2 - 220, HEIGHT // 2 - 110, 440, 56)
    name_rect = pygame.Rect(WIDTH // 2 - 220, HEIGHT // 2 - 30, 440, 56)
    swatches = [
        pygame.Rect(WIDTH // 2 - 168 + index * 64, HEIGHT // 2 + 76, 42, 42)
        for index in range(len(NET_COLORS))
    ]
    pygame.key.start_text_input()
    try:
        while True:
            clock.tick(FPS)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "__quit__"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if address_rect.collidepoint(event.pos):
                        active_field = "address"
                    elif name_rect.collidepoint(event.pos):
                        active_field = "name"
                    for index, rect in enumerate(swatches):
                        if rect.collidepoint(event.pos):
                            selected_color = index
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return None
                    if event.key == pygame.K_TAB:
                        active_field = "name" if active_field == "address" else "address"
                    elif event.key == pygame.K_BACKSPACE:
                        if active_field == "address":
                            address = address[:-1]
                        else:
                            name = name[:-1]
                    elif event.key == pygame.K_RETURN:
                        return address.strip() or "127.0.0.1", name.strip() or "player", NET_COLORS[selected_color]
                    elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        selected_color = (
                            selected_color + (1 if event.key == pygame.K_RIGHT else -1)
                        ) % len(NET_COLORS)
                elif event.type == pygame.TEXTINPUT:
                    if active_field == "address":
                        address = (address + event.text)[:64]
                    else:
                        name = (name + event.text)[:16]

            screen.fill(MENU_BG)
            title = font.render("НАСТРОЙКА ИГРОКА", True, UI_TEXT)
            screen.blit(title, title.get_rect(center=(WIDTH // 2, HEIGHT // 3 - 10)))
            for label, rect, value, placeholder, field_name in (
                ("АДРЕС СЕРВЕРА", address_rect, address, "127.0.0.1", "address"),
                ("НИК", name_rect, name, "player", "name"),
            ):
                label_surface = small_font.render(label, True, (165, 179, 215))
                screen.blit(label_surface, (rect.x, rect.y - 23))
                pygame.draw.rect(screen, (38, 43, 66), rect, border_radius=12)
                pygame.draw.rect(
                    screen, (235, 207, 122) if active_field == field_name else (87, 98, 135),
                    rect, 2, border_radius=12,
                )
                text = font.render(value or placeholder, True,
                                   UI_TEXT if value else (120, 130, 156))
                screen.blit(text, (rect.x + 18, rect.centery - text.get_height() // 2))

            color_label = small_font.render("ЦВЕТ ИГРОКА", True, (165, 179, 215))
            screen.blit(color_label, color_label.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 58)))
            for index, rect in enumerate(swatches):
                pygame.draw.circle(screen, NET_COLORS[index], rect.center, rect.width // 2)
                pygame.draw.circle(
                    screen, (255, 255, 255) if index == selected_color else (36, 40, 59),
                    rect.center, rect.width // 2, 3 if index == selected_color else 2,
                )

            instructions = hint_font.render(
                "Кликните поле и введите текст · ←/→ или клик — цвет · Enter — в лобби",
                True, (180, 180, 200),
            )
            screen.blit(instructions, instructions.get_rect(
                center=(WIDTH // 2, HEIGHT // 2 + 155),
            ))
            note = small_font.render("Пустой адрес подключит к этому компьютеру", True,
                                     (125, 136, 164))
            screen.blit(note, note.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 185)))
            pygame.display.flip()
    finally:
        pygame.key.stop_text_input()