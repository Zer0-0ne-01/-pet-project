# main.py
import math
import random
import struct

import pygame

# --- НАСТРОЙКИ ---
WIDTH, HEIGHT = 1024, 768
FPS = 60

BG_COLOR = (30, 30, 60)
MENU_BG = (20, 20, 40)

PLAYER_SIZE = 50
PLAYER_SPEED = 5
PLAYER_MAX_HP = 100

ENEMY_SIZE = 40
ENEMY_SPEED = 3
ENEMY_DAMAGE_PER_SEC = 40.0   # урон в секунду при касании

# --- ЦВЕТА UI ---
UI_TEXT = (240, 240, 240)
HP_BACK = (60, 60, 60)
HP_FILL = (220, 60, 60)
HP_FILL_LOW = (240, 180, 40)
HP_BORDER = (200, 200, 200)

BUTTON_BG = (60, 80, 140)
BUTTON_BG_HOVER = (90, 120, 190)
BUTTON_BORDER = (200, 220, 255)
BUTTON_TEXT = (255, 255, 255)


# ---------------------------------------------------------------------------
# UI: кнопка меню
# ---------------------------------------------------------------------------
class Button:
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


# ---------------------------------------------------------------------------
# Игровые спрайты
# ---------------------------------------------------------------------------
class Player(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((PLAYER_SIZE, PLAYER_SIZE))
        self.image.fill((80, 200, 120))
        self.rect = self.image.get_rect(topleft=(x, y))
        self.speed = PLAYER_SPEED

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
        self.image = pygame.Surface((ENEMY_SIZE, ENEMY_SIZE))
        self.image.fill((220, 80, 80))
        self.rect = self.image.get_rect(topleft=(x, y))
        self.speed = ENEMY_SPEED

    def update(self):
        self.rect.x += self.speed
        if self.rect.left > WIDTH:
            self.rect.right = 0
            self.rect.y = random.randint(0, HEIGHT - self.rect.height)


# ---------------------------------------------------------------------------
# Звук: синтезируем короткий "пиу" без внешних файлов
# ---------------------------------------------------------------------------
def make_shoot_sound():
    """
    Генерирует короткий нисходящий тон — типичный звук выстрела.
    Если хочешь использовать готовый файл — замени на:
        return pygame.mixer.Sound("assets/shoot.wav")
    """
    if not pygame.mixer.get_init():
        return None

    sample_rate, _fmt, channels = pygame.mixer.get_init()
    duration = 0.12                     # 120 мс
    n_samples = int(sample_rate * duration)

    buf = bytearray()
    for i in range(n_samples):
        t = i / sample_rate
        progress = i / n_samples
        freq = 1200 - 800 * progress    # от 1200 до 400 Гц
        env = math.exp(-t * 25)         # быстрое затухание
        sample = math.sin(2 * math.pi * freq * t) * env
        val = int(32767 * sample * 0.5) # 16-бит signed
        val = max(-32768, min(32767, val))

        # дублируем на все каналы (моно/стерео)
        for _ in range(channels):
            buf += struct.pack('<h', val)

    return pygame.mixer.Sound(buffer=bytes(buf))


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------
def draw_hud(screen, font, hp, score):
    panel = pygame.Rect(15, 15, 300, 96)

    # Полупрозрачный фон панели
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

    ratio = max(0.0, min(1.0, hp / PLAYER_MAX_HP))
    fill_w = int(bar_w * ratio)
    color = HP_FILL if ratio > 0.3 else HP_FILL_LOW
    if fill_w > 0:
        pygame.draw.rect(screen, color, (bar_x, bar_y, fill_w, bar_h), border_radius=5)

    pygame.draw.rect(screen, HP_BORDER, (bar_x, bar_y, bar_w, bar_h), 2, border_radius=5)

    hp_text = font.render(f"{int(hp)}/{PLAYER_MAX_HP}", True, UI_TEXT)
    screen.blit(hp_text, (bar_x + bar_w + 10, bar_y))

    # --- Очки ---
    score_text = font.render(f"Score: {score}", True, UI_TEXT)
    screen.blit(score_text, (panel.x + 14, panel.y + 56))


# ---------------------------------------------------------------------------
# Экран меню
# ---------------------------------------------------------------------------
def run_menu(screen, clock, font_button):
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


# ---------------------------------------------------------------------------
# Игровой цикл
# ---------------------------------------------------------------------------
def run_game(screen, clock, font):
    player = Player(WIDTH // 2, HEIGHT // 2)
    enemies = pygame.sprite.Group(
        Enemy(0, HEIGHT // 3),
        Enemy(-300, 2 * HEIGHT // 3),
    )
    all_sprites = pygame.sprite.Group(player, *enemies)

    # --- звук выстрела ---
    try:
        shoot_sound = make_shoot_sound()
    except Exception as e:                     # noqa: BLE001
        print(f"[SOUND] не удалось создать звук: {e}")
        shoot_sound = None

    score = 0
    score_timer = 0.0
    player_hp = float(PLAYER_MAX_HP)

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
                    # Звук выстрела. См. также:
                    #   pygame.mixer.Sound("assets/shoot.wav").play()
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

        # Столкновение отнимает HP постепенно, пока игрок касается врага
        if pygame.sprite.spritecollideany(player, enemies):
            player_hp -= ENEMY_DAMAGE_PER_SEC * dt
            if player_hp <= 0:
                player_hp = 0
                print("Игра окончена")
                running = False

        # --- 3. РИСОВАНИЕ ---
        screen.fill(BG_COLOR)
        all_sprites.draw(screen)
        draw_hud(screen, font, player_hp, score)

        pygame.display.flip()

    return "menu"


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def main():
    pygame.init()

    # Инициализация аудио — не критично, если звуковой карты нет
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

    pygame.quit()


if __name__ == "__main__":
    main()