from GameObjects.Card.Card import Card, CardControllerBase, UnitCardController
from GameObjects.Card.ChangeStructureCard import (
    ChangeStructureCard,
    ChangeStructureCardController,
)
from GameObjects.Card.SpellCard import SpellCard, SpellCardController


def create_card_controller(
    game, card, parent=None, bg_image="GreenBG1.png"
) -> CardControllerBase:
    """Factory function to create the appropriate card controller based on card type

    Args:
        game: The game instance
        card: Card, SpellCard, or ChangeStructureCard data model
        parent: Optional parent GameObject
        bg_image: Background image for spell cards (default: GreenBG1.png)

    Returns:
        Appropriate CardController subclass for the card type
    """
    if isinstance(card, Card):
        controller = UnitCardController(game, parent)
    elif isinstance(card, ChangeStructureCard):
        controller = ChangeStructureCardController(game, parent, bg_image)
    elif isinstance(card, SpellCard):
        controller = SpellCardController(game, parent, bg_image)
    else:
        raise ValueError(f"Unknown card type: {type(card)}")
    controller.from_card(card)
    return controller
