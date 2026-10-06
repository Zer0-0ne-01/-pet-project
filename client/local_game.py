# client/local_game.py
"""Локальная однопользовательская игра (то, что было в main.py.txt)."""

import math
import random
import struct

import pygame

from shared.config import (
    WIDTH, HEIGHT, FPS,
    LOCAL_BG_COLOR,
    LOCAL_PLAYER_SIZE, LOCAL_PLAYER_SPEED, LOCAL_PLAYER_MAX_HP,
    LOCAL_ENEMY_SIZE, LOCAL_ENEMY_SPEED, LOCAL_ENEMY_DAMAGE_PER_SEC,
)
from client.ui import draw_hud


class Player(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((LOCAL_PLAYER_SIZE, LOCAL_PLAYER_SIZE))
        self.image.fill((80, 200, 120))
        self.rect = self.image.get_rect(topleft=(x, y))
        self.speed = LOCAL_PLAYER_SPEED

    def update(self, keys):
        dx = dy = 0
        if keys[pygame.K_a]:
            dx -= self.speed
        if keys[pygame.K_d]:
            dx += self.speed
        if keys[pygame.K_w]:
            dy -= self.speed
        if keys[pygame.K_s]:
            dy += self.speed

        self.rect.x += dx
        self.rect.y += dy

        self.rect.left = max(0, self.rect.left)
        self.rect.right = min(WIDTH, self.rect.right)
        self.rect.top = max(0, self.rect.top)
        self.rect.bottom = min(HEIGHT, self.rect.bottom)


class Enemy(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((LOCAL_ENEMY_SIZE, LOCAL_ENEMY_SIZE))
        self.image.fill((220, 80, 80))
        self.rect = self.image.get_rect(topleft=(x, y))
        self.speed = LOCAL_ENEMY_SPEED

    def update(self):
        self.rect.x += self.speed

        # Если враг ушёл за правый край — возвращаем его слева
        # на случайной высоте. Без этого враг просто исчезал бы,
        # и игра становилась бы неиграбельной.
        if self.rect.left > WIDTH:
            self.rect.right = 0
            self.rect.y = random.randint(0, HEIGHT - self.rect.height)


def make_shoot_sound():
    """Синтез короткого нисходящего 'пиу' — без внешних файлов."""
    if not pygame.mixer.get_init():
        return None

    sample_rate, _fmt, channels = pygame.mixer.get_init()
    duration = 0.12
    n_samples = int(sample_rate * duration)

    buf = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        progress = i / n_samples
        freq = 1200 - 800 * progress
        env = math.exp(-t * 25)
        sample = math.sin(2 * math.pi * freq * t) * env
        val = int(32767 * sample * 0.5)
        val = max(-32768, min(32767, val))
        for _ in range(channels):
            buf += struct.pack('<h', val)

    return pygame.mixer.Sound(buffer=bytes(buf))


def run_game(screen, clock, font):
    """Возвращает 'menu' | 'quit'."""
    player = Player(WIDTH // 2, HEIGHT // 2)
    enemies = pygame.sprite.Group(
        Enemy(0, HEIGHT // 3),
        Enemy(-300, 2 * HEIGHT // 3),
    )
    all_sprites = pygame.sprite.Group(player, *enemies)

    try:
        shoot_sound = make_shoot_sound()
    except Exception as e:                     # noqa: BLE001
        print(f"[SOUND] не удалось создать звук: {e}")
        shoot_sound = None

    score = 0
    score_timer = 0.0
    player_hp = float(LOCAL_PLAYER_MAX_HP)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        # --- 1. СОБЫТИЯ ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    if shoot_sound is not None:
                        shoot_sound.play()

        # --- 2. ЛОГИКА ---
        keys = pygame.key.get_pressed()
        player.update(keys)
        enemies.update()

        score_timer += dt
        if score_timer >= 1.0:
            score_timer -= 1.0
            score += 1

        if pygame.sprite.spritecollideany(player, enemies):
            player_hp -= LOCAL_ENEMY_DAMAGE_PER_SEC * dt
            if player_hp <= 0:
                player_hp = 0
                print("Игра окончена")
                running = False

        # --- 3. РИСОВАНИЕ ---
        screen.fill(LOCAL_BG_COLOR)
        all_sprites.draw(screen)
        draw_hud(screen, font, player_hp, LOCAL_PLAYER_MAX_HP, score)

        pygame.display.flip()

    return "menu"