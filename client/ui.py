# client/ui.py
"""Переиспользуемые UI-элементы: кнопка, HUD, прицел."""

from functools import lru_cache

import pygame

from shared.config import (
    UI_TEXT, HP_BACK, HP_FILL, HP_FILL_LOW,
    BUTTON_BG, BUTTON_BG_HOVER, BUTTON_BORDER, BUTTON_TEXT,
)

INK = (8, 12, 24)
PANEL = (14, 22, 38)
CYAN = (68, 232, 231)
CORAL = (255, 111, 105)


@lru_cache(maxsize=4)
def _make_arcade_backdrop(width, height):
    background = pygame.Surface((width, height))
    top = (9, 14, 30)
    bottom = (18, 28, 48)
    for y in range(height):
        amount = y / max(1, height - 1)
        color = tuple(round(a + (b - a) * amount) for a, b in zip(top, bottom))
        pygame.draw.line(background, color, (0, y), (width, y))

    horizon = round(height * 0.44)
    grid_color = (25, 53, 73)
    for index in range(-8, 9):
        bottom_x = width // 2 + index * (width // 8)
        pygame.draw.line(background, grid_color, (width // 2, horizon), (bottom_x, height), 1)
    for index in range(1, 10):
        amount = (index / 9) ** 2
        y = round(horizon + (height - horizon) * amount)
        pygame.draw.line(background, grid_color, (0, y), (width, y), 1)

    for center, radius, color in (
        ((width // 2, round(height * 0.34)), round(width * 0.23), (18, 36, 55)),
        ((width // 2, round(height * 0.34)), round(width * 0.18), (20, 41, 59)),
    ):
        pygame.draw.circle(background, color, center, radius, 1)
    return background


def draw_arcade_backdrop(screen, now=0.0, animate=True):
    """Draw the shared neon arena backdrop used by menus and gameplay."""
    width, height = screen.get_size()
    screen.blit(_make_arcade_backdrop(width, height), (0, 0))
    if animate:
        scan_y = int((now * 34) % height)
        scan = pygame.Surface((width, 3), pygame.SRCALPHA)
        scan.fill((*CYAN, 24))
        screen.blit(scan, (0, scan_y))
        pygame.draw.line(screen, (39, 107, 125), (0, scan_y), (width, scan_y), 1)


def draw_panel(surface, rect, fill=PANEL, border=CYAN, radius=12):
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill((*fill, 238))
    surface.blit(panel, rect.topleft)
    pygame.draw.rect(surface, border, rect, 1, border_radius=radius)
    pygame.draw.line(
        surface, border, (rect.x + radius, rect.y + 1),
        (rect.right - radius, rect.y + 1), 2,
    )


def draw_round_scoreboard(surface, players):
    """Show each player's color-coded round score without text labels."""
    panel_width = 88
    row_height = 26
    panel = pygame.Rect(
        surface.get_width() - panel_width - 16, 14,
        panel_width, 12 + row_height * len(players),
    )
    draw_panel(surface, panel, fill=(9, 16, 29), border=(54, 113, 139), radius=8)

    for index, player in enumerate(players.values()):
        y = panel.y + 6 + index * row_height
        marker_left = panel.x + 10
        permanent_squares = player.score_squares
        for square_index in range(permanent_squares):
            marker = pygame.Rect(marker_left + square_index * 20, y + 3, 14, 14)
            pygame.draw.rect(surface, player.color, marker)
            pygame.draw.rect(surface, (235, 248, 255), marker, 1)
        if player.round_streak > 0:
            triangle = (
                (marker_left + permanent_squares * 20, y + 3),
                (marker_left + permanent_squares * 20 + 14, y + 3),
                (marker_left + permanent_squares * 20 + 14, y + 17),
            )
            pygame.draw.polygon(surface, player.color, triangle)
            pygame.draw.polygon(surface, (235, 248, 255), triangle, 1)


class Button:
    """Прямоугольная кнопка с hover-состоянием и action-строкой."""

    def __init__(self, text, rect, font, action):
        self.text = text
        self.rect = pygame.Rect(rect)
        self.font = font
        self.action = action
        self.hovered = False

    def handle_event(self, event):
        """Возвращает action, если по кнопке кликнули, иначе None."""
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return self.action
        return None

    def draw(self, surface):
        bg = BUTTON_BG_HOVER if self.hovered else BUTTON_BG
        border = CORAL if self.hovered else BUTTON_BORDER
        pygame.draw.rect(surface, bg, self.rect, border_radius=10)
        pygame.draw.rect(surface, border, self.rect, 2, border_radius=10)
        pygame.draw.line(
            surface, border, (self.rect.x + 16, self.rect.bottom - 4),
            (self.rect.right - 16, self.rect.bottom - 4), 2,
        )

        text_surf = self.font.render(self.text, True, BUTTON_TEXT)
        text_rect = text_surf.get_rect(center=self.rect.center)
        surface.blit(text_surf, text_rect)


def draw_hud(screen, font, hp, max_hp, score):
    """Минималистичный HUD: только текст и тонкая полоска HP."""
    # Текст HP
    hp_text = font.render(f"HP {int(hp)}", True, UI_TEXT)
    screen.blit(hp_text, (20, 20))

    # Тонкая полоска здоровья под текстом
    bar_x, bar_y = 20, 45
    bar_w, bar_h = 100, 4
    
    pygame.draw.rect(screen, HP_BACK, (bar_x, bar_y, bar_w, bar_h), border_radius=2)
    ratio = 0.0 if max_hp <= 0 else max(0.0, min(1.0, hp / max_hp))
    fill_w = int(bar_w * ratio)
    color = HP_FILL if ratio > 0.3 else HP_FILL_LOW
    if fill_w > 0:
        pygame.draw.rect(screen, color, (bar_x, bar_y, fill_w, bar_h), border_radius=2)

    # Очки
    score_text = font.render(f"SCORE {score}", True, UI_TEXT)
    screen.blit(score_text, (20, 60))


def draw_crosshair(screen, pos):
    """Bright, precise reticle for the neon arena."""
    x, y = pos
    pygame.draw.circle(screen, (10, 18, 28), (x, y), 8, 2)
    pygame.draw.circle(screen, CYAN, (x, y), 2)
    pygame.draw.line(screen, CYAN, (x - 12, y), (x - 5, y), 2)
    pygame.draw.line(screen, CYAN, (x + 5, y), (x + 12, y), 2)
    pygame.draw.line(screen, CYAN, (x, y - 12), (x, y - 5), 2)
    pygame.draw.line(screen, CYAN, (x, y + 5), (x, y + 12), 2)