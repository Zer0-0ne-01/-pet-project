# client/main_menu.py
"""Главное меню и ввод адреса сетевого сервера."""

import pygame

from shared.config import (
    WIDTH, HEIGHT, FPS, UI_TEXT, NET_COLORS,
)
from client.ui import Button, draw_arcade_backdrop, draw_panel


def run_menu(screen, clock, font_button):
    """Возвращает 'play' | 'network' | 'quit'."""
    title_font = pygame.font.SysFont("arial", 72, bold=True)
    hint_font = pygame.font.SysFont("arial", 20)

    buttons = [
        Button("Сетевая игра", (WIDTH // 2 - 180, HEIGHT // 2 - 60, 360, 64),
               font_button, "network"),
        Button("Выход", (WIDTH // 2 - 180, HEIGHT // 2 + 20, 360, 64),
               font_button, "quit"),
    ]

    while True:
        clock.tick(FPS)
        now = pygame.time.get_ticks() / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "quit"

            for b in buttons:
                action = b.handle_event(event)
                if action:
                    return action

        draw_arcade_backdrop(screen, now)

        title = title_font.render("SHUFFLING", True, (233, 249, 255))
        title_rect = title.get_rect(center=(WIDTH // 2, HEIGHT // 3 - 12))
        draw_panel(
            screen,
            pygame.Rect(WIDTH // 2 - 250, HEIGHT // 3 - 68, 500, 138),
            fill=(8, 15, 29), border=(68, 232, 231), radius=20,
        )
        screen.blit(title, title_rect)
        subtitle = hint_font.render("NEON ARENA  /  NETWORK COMBAT", True, (101, 219, 218))
        screen.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, title_rect.bottom + 14)))

        for b in buttons:
            b.draw(screen)

        hint = hint_font.render("Мышь — выбор, Esc — выход", True, (120, 120, 140))
        hint_rect = hint.get_rect(center=(WIDTH // 2, HEIGHT - 40))
        screen.blit(hint, hint_rect)

        pygame.display.flip()


def run_connect_dialog(screen, clock, font, default_name="player"):
    """Запрашивает адрес, ник и косметику игрока перед подключением."""
    address = ""
    name = default_name[:16] or "player"
    selected_color = 0
    selected_eyes = 0
    selected_mouth = 0
    selected_weapon = 0
    active_field = "address"
    small_font = pygame.font.SysFont("arial", 16)
    address_rect = pygame.Rect(WIDTH // 2 - 220, 160, 440, 48)
    name_rect = pygame.Rect(WIDTH // 2 - 220, 222, 440, 48)
    swatches = [
        pygame.Rect(WIDTH // 2 - 168 + index * 64, 304, 42, 42)
        for index in range(len(NET_COLORS))
    ]
    cosmetic_rows = (
        ("ГЛАЗА", ("Точки", "Прищур"), 0),
        ("РОТ", ("Улыбка", "Серьёзный"), 1),
        ("ОРУЖИЕ", ("Пистолет", "Бластер"), 2),
    )
    cosmetic_buttons = [
        (
            pygame.Rect(WIDTH // 2 + 15, 370 + row * 62, 142, 40),
            pygame.Rect(WIDTH // 2 + 169, 370 + row * 62, 142, 40),
        )
        for row in range(len(cosmetic_rows))
    ]
    pygame.key.start_text_input()
    try:
        while True:
            clock.tick(FPS)
            now = pygame.time.get_ticks() / 1000.0
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
                    for row, buttons in enumerate(cosmetic_buttons):
                        for option, rect in enumerate(buttons):
                            if rect.collidepoint(event.pos):
                                if row == 0:
                                    selected_eyes = option
                                elif row == 1:
                                    selected_mouth = option
                                else:
                                    selected_weapon = option
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
                        return (
                            address.strip() or "127.0.0.1",
                            name.strip() or "player",
                            NET_COLORS[selected_color],
                            selected_eyes, selected_mouth, selected_weapon,
                        )
                    elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                        selected_color = (
                            selected_color + (1 if event.key == pygame.K_RIGHT else -1)
                        ) % len(NET_COLORS)
                elif event.type == pygame.TEXTINPUT:
                    if active_field == "address":
                        address = (address + event.text)[:64]
                    else:
                        name = (name + event.text)[:16]

            draw_arcade_backdrop(screen, now)
            form_panel = pygame.Rect(WIDTH // 2 - 340, 76, 680, 620)
            draw_panel(screen, form_panel, fill=(8, 15, 29), border=(68, 232, 231), radius=18)
            title = font.render("СОЗДАЙ СВОЕГО БОЙЦА", True, UI_TEXT)
            screen.blit(title, title.get_rect(center=(WIDTH // 2, form_panel.y + 32)))
            for label, rect, value, placeholder, field_name in (
                ("АДРЕС СЕРВЕРА", address_rect, address, "127.0.0.1", "address"),
                ("НИК", name_rect, name, "player", "name"),
            ):
                label_surface = small_font.render(label, True, (101, 181, 197))
                screen.blit(label_surface, (rect.x, rect.y - 23))
                pygame.draw.rect(screen, (12, 24, 40), rect, border_radius=8)
                pygame.draw.rect(
                    screen, (255, 111, 105) if active_field == field_name else (43, 75, 96),
                    rect, 2, border_radius=9,
                )
                text = font.render(value or placeholder, True,
                                   UI_TEXT if value else (80, 85, 100))
                screen.blit(text, (rect.x + 18, rect.centery - text.get_height() // 2))

            color_label = small_font.render("ЦВЕТ БОЙЦА", True, (101, 181, 197))
            screen.blit(color_label, color_label.get_rect(center=(WIDTH // 2, 284)))
            for index, rect in enumerate(swatches):
                pygame.draw.circle(screen, NET_COLORS[index], rect.center, rect.width // 2)
                pygame.draw.circle(
                    screen, (68, 232, 231) if index == selected_color else (24, 42, 59),
                    rect.center, rect.width // 2, 3 if index == selected_color else 2,
                )

            current_cosmetics = (selected_eyes, selected_mouth, selected_weapon)
            for row, (label, options, style_index) in enumerate(cosmetic_rows):
                y = 370 + row * 62
                label_surface = small_font.render(label, True, (101, 181, 197))
                screen.blit(label_surface, (form_panel.x + 36, y + 12))
                for option, rect in enumerate(cosmetic_buttons[row]):
                    selected = current_cosmetics[style_index] == option
                    pygame.draw.rect(
                        screen, (15, 41, 55) if selected else (12, 24, 40),
                        rect, border_radius=8,
                    )
                    pygame.draw.rect(
                        screen, (68, 232, 231) if selected else (43, 75, 96),
                        rect, 2 if selected else 1, border_radius=8,
                    )
                    option_label = small_font.render(
                        options[option], True,
                        (235, 250, 255) if selected else (139, 179, 200),
                    )
                    screen.blit(option_label, option_label.get_rect(center=rect.center))

            instructions = small_font.render(
                "Кликните варианты · Enter — продолжить · Esc — назад",
                True, (139, 179, 200),
            )
            screen.blit(instructions, instructions.get_rect(center=(WIDTH // 2, 608)))
            note = small_font.render(
                "Пустой адрес подключит к этому компьютеру",
                True, (100, 145, 166),
            )
            screen.blit(note, note.get_rect(center=(WIDTH // 2, 636)))
            pygame.display.flip()
    finally:
        pygame.key.stop_text_input()