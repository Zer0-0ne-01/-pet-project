# client/ui.py
"""Переиспользуемые UI-элементы: кнопка, HUD, прицел."""

import pygame

from shared.config import (
    UI_TEXT, HP_BACK, HP_FILL, HP_FILL_LOW, HP_BORDER,
    BUTTON_BG, BUTTON_BG_HOVER, BUTTON_BORDER, BUTTON_TEXT,
)


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
        pygame.draw.rect(surface, bg, self.rect, border_radius=10)
        pygame.draw.rect(surface, BUTTON_BORDER, self.rect, 2, border_radius=10)

        text_surf = self.font.render(self.text, True, BUTTON_TEXT)
        text_rect = text_surf.get_rect(center=self.rect.center)
        surface.blit(text_surf, text_rect)


def draw_hud(screen, font, hp, max_hp, score):
    """HUD в левом верхнем углу: полоса HP + счётчик очков.

    max_hp передаётся явно — раньше он был константой PLAYER_MAX_HP,
    но после реорганизации это LOCAL_PLAYER_MAX_HP и он не должен
    «протекать» в UI-модуль.
    """
    panel = pygame.Rect(15, 15, 300, 96)

    panel_surf = pygame.Surface(panel.size, pygame.SRCALPHA)
    panel_surf.fill((0, 0, 0, 120))
    screen.blit(panel_surf, panel.topleft)
    pygame.draw.rect(screen, HP_BORDER, panel, 2, border_radius=8)

    # --- Здоровье ---
    label = font.render("HP", True, UI_TEXT)
    screen.blit(label, (panel.x + 14, panel.y + 14))

    bar_x, bar_y = panel.x + 55, panel.y + 14
    bar_w, bar_h = 180, 22

    pygame.draw.rect(screen, HP_BACK, (bar_x, bar_y, bar_w, bar_h), border_radius=5)

    ratio = 0.0 if max_hp <= 0 else max(0.0, min(1.0, hp / max_hp))
    fill_w = int(bar_w * ratio)
    color = HP_FILL if ratio > 0.3 else HP_FILL_LOW
    if fill_w > 0:
        pygame.draw.rect(screen, color, (bar_x, bar_y, fill_w, bar_h), border_radius=5)

    pygame.draw.rect(screen, HP_BORDER, (bar_x, bar_y, bar_w, bar_h), 2, border_radius=5)

    hp_text = font.render(f"{int(hp)}/{int(max_hp)}", True, UI_TEXT)
    screen.blit(hp_text, (bar_x + bar_w + 10, bar_y))

    # --- Очки ---
    score_text = font.render(f"Score: {score}", True, UI_TEXT)
    screen.blit(score_text, (panel.x + 14, panel.y + 56))


def draw_crosshair(screen, pos):
    """Простой крестик-прицел вместо системного курсора."""
    x, y = pos
    color = (230, 230, 230)
    pygame.draw.line(screen, color, (x - 10, y), (x + 10, y), 2)
    pygame.draw.line(screen, color, (x, y - 10), (x, y + 10), 2)
    pygame.draw.circle(screen, color, (x, y), 12, 1)