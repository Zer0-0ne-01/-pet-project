# main.py
import random

import pygame

# --- НАСТРОЙКИ ---
WIDTH, HEIGHT = 1024, 768
FPS = 60

BG_COLOR = (30, 30, 60)

PLAYER_SIZE = 50
PLAYER_SPEED = 5

ENEMY_SIZE = 40
ENEMY_SPEED = 3


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

        # Не выпускаем игрока за границы экрана
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

        # Если враг ушёл за правый край — возвращаем его слева
        # на случайной высоте. Без этого враг просто исчезал бы,
        # и игра становилась бы неиграбельной.
        if self.rect.left > WIDTH:
            self.rect.right = 0
            self.rect.y = random.randint(0, HEIGHT - self.rect.height)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Shuffling — basics")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 24)

    player = Player(WIDTH // 2, HEIGHT // 2)
    enemies = pygame.sprite.Group(
        Enemy(0, HEIGHT // 3),
        Enemy(-300, 2 * HEIGHT // 3),
    )
    all_sprites = pygame.sprite.Group(player, *enemies)

    score = 0
    score_timer = 0.0  # накопитель секунд

    running = True
    while running:
        # dt — сколько секунд прошло с прошлого кадра
        dt = clock.tick(FPS) / 1000.0

        # --- 1. СОБЫТИЯ ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        # --- 2. ЛОГИКА ---
        keys = pygame.key.get_pressed()
        player.update(keys)
        enemies.update()

        # +1 очко в секунду
        score_timer += dt
        if score_timer >= 1.0:
            score_timer -= 1.0
            score += 1

        # Столкновение игрока с любым врагом
        if pygame.sprite.spritecollideany(player, enemies):
            print("Игра окончена")
            running = False

        # --- 3. РИСОВАНИЕ ---
        screen.fill(BG_COLOR)
        all_sprites.draw(screen)

<<<<<<< HEAD
        score_surface = font.render(f"Score: {score}", True, (255, 255, 255))
        screen.blit(score_surface, (20, 20))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
=======
# Когда игровой цикл завершился — корректно выключаем Pygame.
pygame.quit()
>>>>>>> 3a4ede8751e4032e5909ad271223ddeb4d1bf9da
