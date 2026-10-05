# server.py

# UDP-сервер: принимает сообщения от клиентов и выводит их в консоль.
import socket

# --- НАСТРОЙКИ ---
# "0.0.0.0" — слушать на всех сетевых интерфейсах.
# Если хочешь только локально — поставь "127.0.0.1".
HOST = "0.0.0.0"
PORT = 9999
BUFFER_SIZE = 1024  # максимальный размер одного UDP-пакета


def main():
    # socket.AF_INET — IPv4, socket.SOCK_DGRAM — UDP.
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((HOST, PORT))
    print(f"[SERVER] Слушаю на {HOST}:{PORT} (UDP)")

    # Множество известных адресов клиентов (IP, порт).
    # В UDP нет реального соединения — просто запоминаем, кто нам писал.
    clients = set()

    try:
        while True:
            data, addr = server_socket.recvfrom(BUFFER_SIZE)

            try:
                message = data.decode("utf-8")
            except UnicodeDecodeError:
                # Любой мусорный пакет (сканер портов, чужая программа)
                # не должен ронять сервер.
                print(f"[SERVER] Мусорный пакет от {addr} ({len(data)} байт)")
                continue

            if addr not in clients:
                clients.add(addr)
                print(f"[SERVER] Новый клиент: {addr}")

            print(f"[SERVER] Получено от {addr}: {message}")

            response = f"Эхо: {message}"
            server_socket.sendto(response.encode("utf-8"), addr)

    except KeyboardInterrupt:
        print("\n[SERVER] Остановлен пользователем")
    finally:
        server_socket.close()


if __name__ == "__main__":
    main()