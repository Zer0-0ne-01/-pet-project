# client.py

import argparse
import socket

import pygame

# --- НАСТРОЙКИ СЕТИ ---
BUFFER_SIZE = 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1",
                        help="IP сервера")
    parser.add_argument("--port", type=int, default=9999,
                        help="Порт сервера")
    args = parser.parse_args()

    # UDP-сокет клиента. bind() не нужен — ОС сама выделит порт
    # (раньше тут стоял bind на 127.0.0.1, что прибивало сокет к loopback).
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Неблокирующий режим: recvfrom() сразу бросит BlockingIOError,
    # если данных нет, и игра не «замёрзнет» в ожидании пакета.
    client_socket.setblocking(False)

    pygame.init()
    WIDTH, HEIGHT = 1024, 768
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Shuffling — client")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 20)

    log_messages = []

    running = True
    while running:
        # --- 1. СОБЫТИЯ ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    message = "Hello, server!"
                    try:
                        client_socket.sendto(
                            message.encode("utf-8"),
                            (args.host, args.port),
                        )
                        print(f"[CLIENT] Отправлено: {message}")
                    except OSError as e:
                        print(f"[CLIENT] Ошибка отправки: {e}")

        # --- 2. ПРИЁМ ПАКЕТОВ ---
        # Достаём все пакеты, что успели накопиться, за один кадр.
        while True:
            try:
                data, addr = client_socket.recvfrom(BUFFER_SIZE)
            except BlockingIOError:
                break  # данных больше нет — выходим
            except OSError as e:
                print(f"[CLIENT] Ошибка приёма: {e}")
                break

            try:
                message = data.decode("utf-8")
            except UnicodeDecodeError:
                print(f"[CLIENT] Мусорный пакет от {addr}")
                continue

            print(f"[CLIENT] Ответ от {addr}: {message}")
            log_messages.append(message)
            if len(log_messages) > 10:
                log_messages.pop(0)

        # --- 3. РИСОВАНИЕ ---
        screen.fill((0, 0, 100))

        hint = font.render(
            "Пробел — отправить 'Hello, server!', Esc — выход",
            True, (255, 255, 255),
        )
        screen.blit(hint, (20, 20))

        for i, msg in enumerate(log_messages):
            text_surface = font.render(msg, True, (200, 255, 200))
            screen.blit(text_surface, (20, 60 + i * 24))

        pygame.display.flip()
        clock.tick(60)

    client_socket.close()
    pygame.quit()


if __name__ == "__main__":
    main()