class CardController:
    def __init__(self, card_model, card_view) -> None:
        self.card_model = card_model
        self.card_view = card_view

    def set_card_name(self, name) -> None:
        self.card_model.name = name

    def get_card_name(self):
        return self.card_model.name

    def update_view(self) -> None:
        self.card_view.display_card(self.card_model)
