"""Renders a captured demo hand into an animated GIF.

Reads the frame data produced by ``capture_demo_hand.py`` (default
``docs/demo_hand.json``) and draws an omniscient view of the hand —
all hole cards face up, community cards, pots, bets, blinds, and the
showdown result — as an animated GIF (default ``docs/demo.gif``).

Usage:
    python examples/visualisation/render_demo_gif.py
    python examples/visualisation/render_demo_gif.py \
        --input docs/demo_hand.json --output docs/demo.gif
    python examples/visualisation/render_demo_gif.py \
        --stills-dir docs/demo_stills

Requires Pillow (``python -m pip install pillow``).
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont

WIDTH = 960
HEIGHT = 600

BG_COLOUR = (16, 18, 24)
FELT_COLOUR = (31, 104, 62)
FELT_RIM = (18, 62, 38)
RAIL_COLOUR = (64, 40, 24)
WHITE = (240, 242, 245)
MUTED = (148, 154, 163)
GOLD = (232, 190, 80)
AMBER = (255, 191, 0)
RED = (200, 44, 58)
DARK_TEXT = (24, 26, 32)
PLATE_FILL = (34, 38, 48)
PLATE_EDGE = (70, 76, 90)
FOLDED_TINT = (58, 62, 70)

TABLE_CENTRE = (480, 316)
TABLE_RX = 372
TABLE_RY = 224

SEAT_ANGLES = (90.0, 210.0, 330.0)
PLATE_W = 168
PLATE_H = 60

BOARD_CARD_W = 64
BOARD_CARD_H = 90
BOARD_TOP = 272
BOARD_SPACING = 8

HOLE_CARD_W = 54
HOLE_CARD_H = 76
HOLE_RADIUS_FACTOR = 0.62

BET_ANCHORS = ((480, 384), (348, 250), (612, 250))
POT_ANCHOR = (480, 224)

STREET_LABELS = {
    "preflop": "PRE-FLOP",
    "flop": "FLOP",
    "turn": "TURN",
    "river": "RIVER",
    "showdown": "SHOWDOWN",
}

_ACTION_LABELS = {
    "post_small_blind": "posts small blind",
    "post_big_blind": "posts big blind",
    "fold": "folds",
    "check": "checks",
    "call": "calls",
    "bet": "bets",
    "raise_to": "raises to",
}

_FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    """Loads a bold TrueType font with a platform fallback."""
    for path in _FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _polar(
    angle_degrees: float, radius_x: float, radius_y: float
) -> Tuple[int, int]:
    """Converts a table-relative angle into pixel coordinates."""
    import math

    radians = math.radians(angle_degrees)
    x = TABLE_CENTRE[0] + radius_x * math.cos(radians)
    y = TABLE_CENTRE[1] + radius_y * math.sin(radians)
    return int(x), int(y)


def _draw_suit(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    s: int,
    suit: str,
    colour: Tuple[int, int, int],
) -> None:
    """Draws a suit pip with vector primitives."""
    if suit == "D":
        draw.polygon(
            [(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)],
            fill=colour,
        )
    elif suit == "H":
        r = s * 0.52
        draw.ellipse(
            [cx - s, cy - s * 0.62, cx - s + 2 * r, cy - s * 0.62 + 2 * r],
            fill=colour,
        )
        draw.ellipse(
            [cx + s - 2 * r, cy - s * 0.62, cx + s, cy - s * 0.62 + 2 * r],
            fill=colour,
        )
        draw.polygon(
            [(cx - s, cy - s * 0.1), (cx + s, cy - s * 0.1), (cx, cy + s)],
            fill=colour,
        )
    elif suit == "S":
        r = s * 0.52
        draw.polygon(
            [(cx - s, cy + s * 0.18), (cx + s, cy + s * 0.18), (cx, cy - s)],
            fill=colour,
        )
        draw.ellipse(
            [cx - s, cy - s * 0.14, cx - s + 2 * r, cy - s * 0.14 + 2 * r],
            fill=colour,
        )
        draw.ellipse(
            [cx + s - 2 * r, cy - s * 0.14, cx + s, cy - s * 0.14 + 2 * r],
            fill=colour,
        )
        draw.polygon(
            [
                (cx - s * 0.22, cy + s * 0.95),
                (cx + s * 0.22, cy + s * 0.95),
                (cx, cy + s * 0.3),
            ],
            fill=colour,
        )
    else:
        r = s * 0.46
        draw.ellipse([cx - r, cy - s - r, cx + r, cy - s + r], fill=colour)
        draw.ellipse(
            [cx - s - r, cy + s * 0.2 - r, cx - s + r, cy + s * 0.2 + r],
            fill=colour,
        )
        draw.ellipse(
            [cx + s - r, cy + s * 0.2 - r, cx + s + r, cy + s * 0.2 + r],
            fill=colour,
        )
        draw.polygon(
            [
                (cx - s * 0.2, cy + s * 0.95),
                (cx + s * 0.2, cy + s * 0.95),
                (cx, cy + s * 0.25),
            ],
            fill=colour,
        )


def _draw_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    code: Optional[str],
    dimmed: bool = False,
) -> None:
    """Draws a playing card face, back, or dimmed folded card."""
    face = (150, 152, 158) if dimmed else (232, 235, 240)
    draw.rounded_rectangle(
        [x, y, x + w, y + h], radius=6, fill=face, outline=(56, 60, 70)
    )
    if code is None:
        inner = (24, 44, 84)
        draw.rounded_rectangle(
            [x + 5, y + 5, x + w - 5, y + h - 5],
            radius=4,
            fill=inner,
            outline=(150, 122, 60),
        )
        draw.line([x + 10, y + h - 10, x + w - 10, y + 10], fill=(58, 82, 128))
        draw.line([x + 10, y + 10, x + w - 10, y + h - 10], fill=(58, 82, 128))
        return

    red = code[1] in "HD"
    if dimmed:
        colour = (104, 106, 112)
    elif red:
        colour = RED
    else:
        colour = (26, 28, 34)
    draw.text((x + 5, y + 3), code[0], font=_font(int(w * 0.46)), fill=colour)
    _draw_suit(
        draw, x + w // 2, y + int(h * 0.64), int(w * 0.26), code[1], colour
    )


def _draw_chip_stack(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    amount: int,
) -> None:
    """Draws a small chip stack with an amount label beside it."""
    chips = min(3, max(1, amount // 25))
    chip_colours = [(214, 68, 84), (66, 110, 190), (86, 158, 92)]
    for index in range(chips):
        offset = index * 4
        colour = chip_colours[index % len(chip_colours)]
        draw.ellipse(
            [x - 13, y - 5 - offset, x + 13, y + 5 - offset],
            fill=colour,
            outline=(20, 22, 28),
        )
    draw.text((x + 20, y - 9), f"{amount:,}", font=_font(17), fill=WHITE)


def _describe_event(event: Mapping[str, Any], names: Mapping[str, str]) -> str:
    """Formats a single captured event as caption text."""
    event_type = event.get("type")
    if event_type == "action":
        who = names.get(str(event.get("player_id")), "?")
        action = str(event.get("action"))
        amount = event.get("amount")
        label = _ACTION_LABELS.get(action, action)
        if amount is None:
            return f"{who} {label}"
        return f"{who} {label} {amount}"
    if event_type == "street_advanced":
        street = str(event.get("street", "")).capitalize()
        board = " ".join(event.get("board") or [])
        return f"{street}   {board}"
    if event_type == "showdown":
        results = event.get("results") or []
        winners = [r for r in results if (r.get("winnings") or 0) > 0]
        if not winners:
            return "Showdown"
        total = sum(int(w.get("winnings", 0)) for w in winners)
        winners_text = " & ".join(
            names.get(str(w.get("player_id")), "?") for w in winners
        )
        hand = str(winners[0].get("hand") or "")
        if hand in ("Won by Fold", "Folded"):
            return f"{winners_text} wins {total:,} — everyone folded"
        return f"{winners_text} wins {total:,} with {hand}"
    return str(event_type or "")


def _fit_text(
    draw: ImageDraw.ImageDraw, text: str, max_width: int, size: int
) -> str:
    """Truncates text with an ellipsis to fit the given width."""
    if draw.textlength(text, font=_font(size)) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=_font(size)) > max_width:
        text = text[:-1]
    return text + "…"


class DemoGifRenderer:
    """Draws captured hand frames as GIF images."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        """Stores the captured payload and derives seat labels."""
        self.data = data
        meta = data["meta"]
        self.meta = meta
        self.names = {
            player_id: f"Bot {index + 1}"
            for index, player_id in enumerate(meta["player_ids"])
        }

    def render(
        self,
    ) -> Tuple[List[Image.Image], List[int]]:
        """Builds every GIF frame with its duration in milliseconds."""
        images: List[Image.Image] = []
        durations: List[int] = []

        title = self._title_frame()
        images.append(title)
        durations.append(2200)

        frames = self.data["frames"]
        for index, frame in enumerate(frames):
            results = self._showdown_results(frame)
            if results is not None and index > 0:
                reveal = self._reveal_frame(frames[index - 1], frame)
                image = self._scene_image(
                    reveal, results=results, reveal_only=True
                )
                images.append(image)
                durations.append(2000)

            image = self._scene_image(frame, results=results)
            images.append(image)
            durations.append(self._duration(frame))

        return images, durations

    def _title_frame(self) -> Image.Image:
        """Builds the opening title card."""
        image = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOUR)
        draw = ImageDraw.Draw(image)
        self._draw_table(draw)
        title = "No-Limit Texas Hold'em"
        sub = (
            f"3 bots  •  {self.meta['starting_stack']:,} chips  •  "
            f"blinds {self.meta['small_blind']}/{self.meta['big_blind']}"
        )
        draw.text(
            (480, 250),
            title,
            font=_font(44),
            fill=WHITE,
            anchor="mm",
        )
        draw.text((480, 305), sub, font=_font(20), fill=GOLD, anchor="mm")
        draw.text(
            (480, 345),
            "a real hand played on the match server",
            font=_font(16),
            fill=MUTED,
            anchor="mm",
        )
        return image

    def _scene_image(
        self,
        frame: Mapping[str, Any],
        *,
        results: Optional[Mapping[str, Mapping[str, Any]]] = None,
        reveal_only: bool = False,
    ) -> Image.Image:
        """Draws one captured (or synthesised) frame."""
        image = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOUR)
        draw = ImageDraw.Draw(image)
        self._draw_table(draw)
        self._draw_header(draw, frame)
        self._draw_board(draw, frame)
        self._draw_pot(draw, frame)
        for seat_index, player in enumerate(frame["players"]):
            self._draw_seat(
                draw, seat_index, player, frame, results, reveal_only
            )
        caption = (
            "   •   ".join(
                _describe_event(event, self.names) for event in frame["events"]
            )
            or "Showdown — cards on their backs"
        )
        gold = results is not None and not reveal_only
        self._draw_caption(draw, caption, gold=gold)
        return image

    def _draw_table(self, draw: ImageDraw.ImageDraw) -> None:
        """Draws the static table, rail, and felt."""
        cx, cy = TABLE_CENTRE
        draw.ellipse(
            [
                cx - TABLE_RX - 16,
                cy - TABLE_RY - 16,
                cx + TABLE_RX + 16,
                cy + TABLE_RY + 16,
            ],
            fill=RAIL_COLOUR,
        )
        draw.ellipse(
            [
                cx - TABLE_RX - 6,
                cy - TABLE_RY - 6,
                cx + TABLE_RX + 6,
                cy + TABLE_RY + 6,
            ],
            fill=FELT_RIM,
        )
        draw.ellipse(
            [cx - TABLE_RX, cy - TABLE_RY, cx + TABLE_RX, cy + TABLE_RY],
            fill=FELT_COLOUR,
        )

    def _draw_header(
        self, draw: ImageDraw.ImageDraw, frame: Mapping[str, Any]
    ) -> None:
        """Draws the title, street badge, and stakes line."""
        draw.text(
            (24, 18),
            "No-Limit Texas Hold'em",
            font=_font(22),
            fill=WHITE,
        )
        draw.text(
            (WIDTH - 24, 24),
            f"blinds {self.meta['small_blind']}/{self.meta['big_blind']}"
            f"  •  stacks {self.meta['starting_stack']:,}",
            font=_font(15),
            fill=MUTED,
            anchor="ra",
        )
        street = STREET_LABELS.get(
            str(frame.get("street")), str(frame.get("street", "")).upper()
        )
        pill_w = 150
        draw.rounded_rectangle(
            [480 - pill_w // 2, 14, 480 + pill_w // 2, 44],
            radius=15,
            fill=(40, 45, 56),
            outline=PLATE_EDGE,
        )
        draw.text((480, 29), street, font=_font(16), fill=GOLD, anchor="mm")

    def _draw_board(
        self, draw: ImageDraw.ImageDraw, frame: Mapping[str, Any]
    ) -> None:
        """Draws the five community card slots."""
        board = list(frame.get("board") or [])
        total_w = 5 * BOARD_CARD_W + 4 * BOARD_SPACING
        start_x = 480 - total_w // 2
        for slot in range(5):
            x = start_x + slot * (BOARD_CARD_W + BOARD_SPACING)
            code = board[slot] if slot < len(board) else None
            _draw_card(draw, x, BOARD_TOP, BOARD_CARD_W, BOARD_CARD_H, code)

    def _draw_pot(
        self, draw: ImageDraw.ImageDraw, frame: Mapping[str, Any]
    ) -> None:
        """Draws the pot chip and amount above the board."""
        pot = int(frame.get("pot", 0))
        if frame.get("street") == "showdown" and pot == 0:
            return
        x, y = POT_ANCHOR
        draw.ellipse(
            [x - 15, y - 15, x + 15, y + 15],
            fill=(214, 168, 60),
            outline=(24, 22, 28),
        )
        draw.ellipse(
            [x - 9, y - 9, x + 9, y + 9],
            outline=(160, 122, 40),
        )
        draw.text((x + 24, y), f"Pot {pot:,}", font=_font(20), fill=WHITE)

    def _draw_seat(
        self,
        draw: ImageDraw.ImageDraw,
        seat_index: int,
        player: Mapping[str, Any],
        frame: Mapping[str, Any],
        results: Optional[Mapping[str, Mapping[str, Any]]],
        reveal_only: bool,
    ) -> None:
        """Draws one seat: plate, hole cards, bet, and badges."""
        angle = SEAT_ANGLES[seat_index]
        px, py = _polar(angle, TABLE_RX * 0.9, TABLE_RY * 0.88)
        plate = [
            px - PLATE_W // 2,
            py - PLATE_H // 2,
            px + PLATE_W // 2,
            py + PLATE_H // 2,
        ]

        player_id = str(player["id"])
        name = self.names.get(player_id, player_id)
        folded = bool(player.get("folded"))
        is_winner = (
            results is not None
            and not reveal_only
            and int((results.get(player_id) or {}).get("winnings", 0)) > 0
        )
        is_acting = (
            frame.get("acting_index") == seat_index
            and frame.get("status") == "running"
        )

        plate_fill = FOLDED_TINT if folded else PLATE_FILL
        if is_winner:
            plate_fill = (74, 60, 22)
        draw.rounded_rectangle(
            plate, radius=12, fill=plate_fill, outline=PLATE_EDGE, width=2
        )
        if is_winner:
            draw.rounded_rectangle(plate, radius=12, outline=GOLD, width=4)
        elif is_acting:
            draw.rounded_rectangle(plate, radius=12, outline=AMBER, width=3)

        name_colour = MUTED if folded else WHITE
        if is_acting or is_winner:
            name_colour = GOLD if is_winner else AMBER
        draw.text(
            (px, py - 12), name, font=_font(18), fill=name_colour, anchor="mm"
        )
        stack_text = f"{int(player['stack']):,}"
        draw.text(
            (px, py + 14),
            stack_text,
            font=_font(17),
            fill=MUTED if folded else (170, 220, 185),
            anchor="mm",
        )
        if player.get("all_in"):
            badge_w = 62
            draw.rounded_rectangle(
                [
                    px - badge_w // 2,
                    plate[1] - 16,
                    px + badge_w // 2,
                    plate[1] - 2,
                ],
                radius=7,
                fill=RED,
            )
            draw.text(
                (px, plate[1] - 9),
                "ALL IN",
                font=_font(11),
                fill=WHITE,
                anchor="mm",
            )

        if results is not None and player_id in results:
            hand = str(results[player_id].get("hand") or "")
            if hand and hand != "Folded":
                text = _fit_text(draw, hand, 150, 14)
                draw.text(
                    (px, plate[3] + 16),
                    text,
                    font=_font(14),
                    fill=GOLD if is_winner else (200, 206, 214),
                    anchor="mm",
                )
        if is_winner:
            winnings = int(results[player_id].get("winnings", 0))
            label = f"wins {winnings:,}"
            badge_w = 110
            badge_y = plate[1] - 34
            draw.rounded_rectangle(
                [px - badge_w // 2, badge_y, px + badge_w // 2, badge_y + 20],
                radius=10,
                fill=GOLD,
            )
            draw.text(
                (px, badge_y + 10),
                label,
                font=_font(13),
                fill=DARK_TEXT,
                anchor="mm",
            )

        if self.meta.get("dealer_index") == seat_index:
            dx = px + (PLATE_W // 2 - 4 if angle != 210 else -PLATE_W // 2 + 4)
            dy = plate[1] - 12
            draw.ellipse([dx - 11, dy - 11, dx + 11, dy + 11], fill=WHITE)
            draw.text(
                (dx, dy), "D", font=_font(13), fill=DARK_TEXT, anchor="mm"
            )

        hole_cards = list(player.get("hole_cards") or [])
        hx, hy = _polar(
            angle, TABLE_RX * HOLE_RADIUS_FACTOR, TABLE_RY * HOLE_RADIUS_FACTOR
        )
        hx -= HOLE_CARD_W + 2
        for card_index in range(2):
            code = (
                hole_cards[card_index]
                if card_index < len(hole_cards)
                else None
            )
            _draw_card(
                draw,
                hx + card_index * (HOLE_CARD_W + 6),
                hy - HOLE_CARD_H // 2,
                HOLE_CARD_W,
                HOLE_CARD_H,
                code,
                dimmed=folded,
            )

        bet = int(player.get("bet", 0))
        if bet > 0:
            bx, by = BET_ANCHORS[seat_index]
            _draw_chip_stack(draw, bx, by, bet)

    def _draw_caption(
        self, draw: ImageDraw.ImageDraw, caption: str, *, gold: bool
    ) -> None:
        """Draws the bottom caption band."""
        draw.rectangle([0, 556, WIDTH, HEIGHT], fill=(12, 13, 17))
        draw.line([0, 556, WIDTH, 556], fill=PLATE_EDGE)
        text = _fit_text(draw, caption, 880, 20)
        draw.text(
            (480, 578),
            text,
            font=_font(20),
            fill=GOLD if gold else WHITE,
            anchor="mm",
        )

    def _showdown_results(
        self, frame: Mapping[str, Any]
    ) -> Optional[Dict[str, Mapping[str, Any]]]:
        """Extracts showdown results keyed by player id, if any."""
        for event in frame["events"]:
            if event.get("type") == "showdown":
                return {
                    str(result["player_id"]): result
                    for result in event.get("results") or []
                }
        return None

    def _reveal_frame(
        self,
        previous: Mapping[str, Any],
        showdown_frame: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Synthesises a pre-payout frame: full board, pot still visible."""
        return {
            "street": "showdown",
            "board": list(showdown_frame.get("board") or []),
            "pot": previous.get("pot", 0),
            "status": "finished",
            "acting_index": None,
            "players": [dict(player) for player in previous["players"]],
            "events": [],
        }

    def _duration(self, frame: Mapping[str, Any]) -> int:
        """Picks a GIF frame duration from the frame's event types."""
        types = {event.get("type") for event in frame["events"]}
        if "showdown" in types:
            return 3600
        if "street_advanced" in types:
            return 1700
        actions = [event.get("action") for event in frame["events"]]
        if actions and all(
            str(a).startswith("post_") for a in actions if a is not None
        ):
            return 1700
        return 1100


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a captured demo hand as an animated GIF."
    )
    parser.add_argument("--input", default="docs/demo_hand.json")
    parser.add_argument("--output", default="docs/demo.gif")
    parser.add_argument(
        "--stills-dir",
        default=None,
        help="Optional directory to write one PNG per GIF frame.",
    )
    return parser.parse_args()


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    args = _parse_args()
    input_path = _resolve(args.input)
    output_path = _resolve(args.output)

    data = json.loads(input_path.read_text())
    renderer = DemoGifRenderer(data)
    images, durations = renderer.render()

    if args.stills_dir:
        stills_dir = _resolve(args.stills_dir)
        stills_dir.mkdir(parents=True, exist_ok=True)
        for index, image in enumerate(images):
            image.save(stills_dir / f"frame_{index:02d}.png")

    images[0].save(
        output_path,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    size_kb = output_path.stat().st_size / 1024
    print(
        f"[render] wrote {len(images)} frames "
        f"({sum(durations) / 1000:.1f}s loop) to {output_path} "
        f"({size_kb:.0f} KB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
