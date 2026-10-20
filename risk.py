
"""
BINARY ENGINE - DAILY RISK MANAGER
Persistent daily limits for testing.

Maximum completed trades per day: 6
Maximum losses per day: 2

TEST ONLY: This module does not place trades.
"""

import json
import tempfile
from datetime import date
from pathlib import Path


class DailyRiskManager:
    def __init__(self, max_trades=6, max_losses=2, state_file=None):
        if max_trades < 1 or max_losses < 1:
            raise ValueError("Risk limits must be at least 1.")

        self.max_trades = max_trades
        self.max_losses = max_losses

        if state_file is None:
            state_file = Path(__file__).resolve().parent / "risk_state.json"

        self.state_file = Path(state_file)

        self.trades_today = 0
        self.losses_today = 0
        self.today = date.today().isoformat()

        self._load_state()

    def _reset_for_today(self):
        self.today = date.today().isoformat()
        self.trades_today = 0
        self.losses_today = 0
        self._save_state()

    def _load_state(self):
        if not self.state_file.exists():
            self._save_state()
            return

        try:
            data = json.loads(
                self.state_file.read_text(encoding="utf-8")
            )

            saved_date = data.get("date")
            trades = data.get("trades_today")
            losses = data.get("losses_today")

            if (
                not isinstance(saved_date, str)
                or type(trades) is not int
                or type(losses) is not int
                or trades < 0
                or losses < 0
                or losses > trades
            ):
                raise ValueError("Invalid risk state data.")

            if saved_date != date.today().isoformat():
                self._reset_for_today()
                return

            self.today = saved_date
            self.trades_today = trades
            self.losses_today = losses

        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            # Fail safely: do not allow trading if saved limits
            # cannot be trusted.
            self.today = date.today().isoformat()
            self.trades_today = self.max_trades
            self.losses_today = self.max_losses
            self._save_state()

    def _save_state(self):
        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        data = {
            "date": self.today,
            "trades_today": self.trades_today,
            "losses_today": self.losses_today,
        }

        temporary_file = self.state_file.with_suffix(".tmp")

        temporary_file.write_text(
            json.dumps(data, indent=4),
            encoding="utf-8",
        )

        temporary_file.replace(self.state_file)

    def can_trade(self):
        # If the calendar day has changed, reset the daily limits.
        current_date = date.today().isoformat()

        if current_date != self.today:
            self._reset_for_today()

        if self.losses_today >= self.max_losses:
            return False, "STOP: Daily loss limit reached."

        if self.trades_today >= self.max_trades:
            return False, "STOP: Daily trade limit reached."

        return True, "OK: Trading limit available."

    def record_trade(self, won):
        if not isinstance(won, bool):
            raise ValueError("won must be True or False.")

        allowed, message = self.can_trade()

        if not allowed:
            raise RuntimeError(
                "Trade result not recorded. " + message
            )

        self.trades_today += 1

        if not won:
            self.losses_today += 1

        self._save_state()

    def show_status(self):
        allowed, message = self.can_trade()

        print("=== BINARY ENGINE RISK STATUS ===")
        print("Date:", self.today)
        print("Trades today:", self.trades_today)
        print("Losses today:", self.losses_today)
        print("Maximum trades:", self.max_trades)
        print("Maximum losses:", self.max_losses)
        print("Can trade:", allowed)
        print("Status:", message)
        print("State file:", self.state_file)


def run_safe_test():
    # Use a temporary file so the test cannot alter the real
    # daily risk state.
    with tempfile.TemporaryDirectory() as folder:
        test_file = Path(folder) / "risk_test.json"

        print("BINARY ENGINE - RISK MANAGER TEST")
        print("No real trades will be placed.")
        print()

        risk = DailyRiskManager(state_file=test_file)

        risk.record_trade(won=True)
        risk.record_trade(won=False)
        risk.record_trade(won=True)

        print("--- Status after 3 test trades ---")
        risk.show_status()

        print()
        print("--- Reloading saved test state ---")

        reloaded_risk = DailyRiskManager(
            state_file=test_file
        )
        reloaded_risk.show_status()

        print()
        print("--- Testing the 2-loss safety stop ---")

        reloaded_risk.record_trade(won=False)

        allowed, message = reloaded_risk.can_trade()
        print("Can trade:", allowed)
        print("Status:", message)

        if not allowed:
            print("PASS: Daily safety stop is working.")
        else:
            print("FAIL: Daily safety stop did not activate.")


if __name__ == "__main__":
    run_safe_test()
