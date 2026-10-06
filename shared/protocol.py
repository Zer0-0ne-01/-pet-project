# shared/protocol.py
"""Строковые типы сообщений UDP-протокола Shuffling.

Вынесены в отдельный модуль, чтобы сервер и клиент не расходились
в «магических строках» и чтобы легко было добавлять новые типы
(например, "shoot", "card_pick" на следующих этапах).
"""

# клиент → сервер
MSG_JOIN = "join"
MSG_INPUT = "input"
MSG_SHOOT = "shoot"
MSG_LEAVE = "leave"

# сервер → клиент
MSG_WELCOME = "welcome"
MSG_STATE = "state"