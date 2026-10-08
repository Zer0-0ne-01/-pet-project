# shared/protocol.py
"""Строковые типы сообщений UDP-протокола Shuffling."""

# клиент → сервер
MSG_JOIN = "join"
MSG_INPUT = "input"
MSG_SHOOT = "shoot"
MSG_LEAVE = "leave"

# сервер → клиент
MSG_WELCOME = "welcome"
MSG_STATE = "state"
MSG_REJECT = "reject"