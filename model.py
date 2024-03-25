# models.py
class Card:
    def __init__(self, name, rulings) -> None:
        self.name = name
        self.rulings = rulings

    # other methods related to Card


class Ruling:
    def __init__(self, type, content) -> None:
        self.type = type
        self.content = content

    # other methods related to Ruling
