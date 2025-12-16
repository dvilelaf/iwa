import runpy
import sys
from unittest.mock import patch


def test_main_execution():
    """Test that python -m iwa executes the CLI."""
    # We mock iwa.core.cli.iwa_cli to verify it gets called
    with patch("iwa.core.cli.iwa_cli") as mock_cli:
        # We also need to mock sys.argv to avoid interfering with pytest args
        with patch.object(sys, "argv", ["iwa"]):
            runpy.run_module("iwa", run_name="__main__")
            mock_cli.assert_called_once()
