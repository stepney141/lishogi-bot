import importlib
import logging

import pytest

lishogi_bot = importlib.import_module("lishogi-bot")

GAME_ID = "abcd1234"


@pytest.fixture
def bot_log(tmp_path):
    """Logs the root logger to a bot log file at INFO, as --logfile does, and restores it afterwards."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    path = tmp_path / "lishogi-bot.log"
    handler = lishogi_bot.log_file_handler(str(path))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield path
    handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def log(message):
    logging.getLogger("engine_ctrl.usi").info(message)


def test_a_game_is_logged_to_its_own_file_and_not_to_the_bot_log(bot_log, tmp_path):
    games = tmp_path / "games"
    with lishogi_bot.game_log_file(GAME_ID, str(games)):
        log("bestmove 7g7f")
    log("Accept challenge")
    game_text = (games / f"{GAME_ID}.log").read_text()
    bot_text = bot_log.read_text()
    assert "bestmove 7g7f" in game_text
    assert "Accept challenge" not in game_text
    assert "Accept challenge" in bot_text
    assert "bestmove 7g7f" not in bot_text


def test_a_reconnected_game_appends_to_its_file(bot_log, tmp_path):
    games = str(tmp_path / "games")
    for message in ["first connection", "second connection"]:
        with lishogi_bot.game_log_file(GAME_ID, games):
            log(message)
    text = (tmp_path / "games" / f"{GAME_ID}.log").read_text()
    assert text.index("first connection") < text.index("second connection")


def test_without_a_game_log_dir_the_game_is_logged_to_no_file(bot_log, tmp_path):
    with lishogi_bot.game_log_file(GAME_ID, None):
        log("bestmove 7g7f")
    log("Accept challenge")
    assert "bestmove 7g7f" not in bot_log.read_text()
    assert list(tmp_path.iterdir()) == [bot_log]


def test_a_failed_game_restores_the_bot_log(bot_log, tmp_path):
    handlers = logging.getLogger().handlers[:]
    with pytest.raises(RuntimeError):
        with lishogi_bot.game_log_file(GAME_ID, str(tmp_path / "games")):
            log("bestmove 7g7f")
            raise RuntimeError("stream failed")
    assert logging.getLogger().handlers == handlers
    log("after the game")
    assert "after the game" in bot_log.read_text()
    assert "after the game" not in (tmp_path / "games" / f"{GAME_ID}.log").read_text()


def test_play_game_logs_the_game_to_its_own_file(bot_log, tmp_path, monkeypatch):
    def run_game(li, game_id, *_):
        log(f"+++ Playing {game_id}")

    monkeypatch.setattr(lishogi_bot, "run_game", run_game)
    lishogi_bot.play_game.__wrapped__(None, GAME_ID, None, None, None, None, None, None, lambda *_: None, logging.INFO, str(tmp_path / "games"))
    assert f"+++ Playing {GAME_ID}" in (tmp_path / "games" / f"{GAME_ID}.log").read_text()
